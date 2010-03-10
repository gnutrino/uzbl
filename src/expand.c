#include "uzbl-core.h"

static char *expand_var(char *str);
static char *expand_cmd(char *str);
static char *expand_js(char *str);
static char *expand_esc(char *str);
static char *expando(const char **s);  /* XXX: needs a better name (badly!) */

gchar *
expand(const char *s) {
    char *ret = NULL;
    GString *buf = g_string_new("");

    while(s && *s) {
        switch(*s) {
            case '\\':
                g_string_append_c(buf, *++s);
                s++;
                break;

            case '@':
                s++;
                ret = expando(&s);
				if(!ret) { /* malformed string */
					g_string_free(buf, TRUE);
					/* fail soft(ish) */
					return g_strdup("");
				}
                g_string_append(buf, ret);
                g_free(ret);
                break;

            default:
                g_string_append_c(buf, *s);
                s++;
                break;
        }
    }
    return g_string_free(buf, FALSE);
}

static char *
expando(const char **s) {
    const char *tmp = *s;
    char *end_simple_var = "^°!\"§$%&/()=?'`'+~*'#-.:,;@<>| \\{}[]¹²³¼½";
    char *vend = NULL;
    char *(*func)(char *) = NULL;

	/* 
	 * XXX: if vend ends up NULL (i.e a closing token is not found and hence the
	 * string is malformed) *s gets set to an invalid value - we don't handle
	 * this very gracefully and the whole expansion returns an empty string
	 * which may come as a surprise to the caller...
	 */
    switch(*tmp) {
        case '{':
            ++tmp;
            vend = strchr(tmp, '}');
            func = expand_var;
            *s = vend + 1;
            break;
        case '(':
            ++tmp;
            vend = strstr(tmp, ")@");
            func = expand_cmd;
            *s = vend + 2;
            break;
        case '<':
            ++tmp;
            vend = strstr(tmp, ">@");
            func = expand_js;
            *s = vend + 2;
            break;
        case '[':
            ++tmp;
            vend = strstr(tmp, "]@");
            func = expand_esc;
            *s = vend + 2;
            break;
        default:
            /*
             * XXX: This should match against characters that *can*
             * be part of a variable name rather than those that
             * can't
             */
            vend = strpbrk(tmp, end_simple_var);
            if(!vend) vend = strchr(tmp, '\0');
            func = expand_var;
            *s = vend;
            break;
    }
    if(!vend) {
        return NULL;
    }
    return func(g_strndup(tmp, vend - tmp));
}

static char *
expand_var(char *str) {

    uzbl_cmdprop *c = g_hash_table_lookup(uzbl.comm.proto_var, str);
    g_free(str);

    if(!c) {
        return g_strdup("");
    }
    if(c->type == TYPE_STR && *c->ptr.s != NULL) {
        /* XXX: what if c->ptr.* == NULL? (shouldn't happen but...) */
        return g_strdup(*c->ptr.s);
    }
    else if(c->type == TYPE_INT) {
        return itos(*c->ptr.i);
    }
    else if(c->type == TYPE_FLOAT) {
        return ftos(*c->ptr.f);
    }
    return g_strdup("");
}

static char *
expand_cmd(char *str) {

    char *mycmd = expand(str);
    g_free(str);

    char *cmd_stdout = NULL;
    GError *err = NULL;

    /* execute program directly */
    if(mycmd[0] == '+') {
        g_spawn_command_line_sync(mycmd+1, &cmd_stdout, NULL, NULL, &err);
        g_free(mycmd);
    }
    /* execute program through shell, quote it first */
    else {
        gchar *quoted = g_shell_quote(mycmd);
        gchar *tmp = g_strdup_printf("%s %s",
                uzbl.behave.shell_cmd?uzbl.behave.shell_cmd:"/bin/sh -c",
                quoted);
        g_spawn_command_line_sync(tmp, &cmd_stdout, NULL, NULL, &err);
        g_free(mycmd);
        g_free(quoted);
        g_free(tmp);
    }

    if (err) {
        g_printerr("error running command: %s\n", err->message);
        g_error_free (err);
        g_free(cmd_stdout);
        return g_strdup("");
    }

    size_t len = strlen(cmd_stdout);

    if(len > 0 && cmd_stdout[len-1] == '\n')
        cmd_stdout[--len] = '\0'; /* strip trailing newline */
    return cmd_stdout;
}

static char *
expand_js(char *str) {

    char *mycmd = expand(str);
    g_free(str);

    GString *js_ret = g_string_new("");

    /* read JS from file */
    if(mycmd[0] == '+') {
        GArray *tmp = g_array_new(TRUE, FALSE, sizeof(gchar *));
        /* glib has to make life difficult by requiring an lvalue... */
        char *s = g_strdup(mycmd + 1);
        g_free(mycmd);
        g_array_append_val(tmp, s);

        run_external_js(uzbl.gui.web_view, tmp, js_ret);
        g_array_free(tmp, TRUE);
    }
    /* JS from string */
    else {
        eval_js(uzbl.gui.web_view, mycmd, js_ret, "(command)");
        g_free(mycmd);
    }

    if(js_ret->str) {
        return g_string_free(js_ret, FALSE);
    }
    else {
        g_string_free(js_ret, TRUE);
        return g_strdup("");
    }
}

static char *
expand_esc(char *str) {

    char *mycmd = expand(str);
    g_free(str);
    char *escaped = g_markup_escape_text(mycmd, strlen(mycmd));
    g_free(mycmd);
    return escaped;
}

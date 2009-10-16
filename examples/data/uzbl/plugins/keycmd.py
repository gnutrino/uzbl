import re

# Map these functions/variables in the plugins namespace to the uzbl object.
__export__ = ['clear_keycmd', 'set_keycmd', 'set_cursor_pos', 'get_keylet']

# Regular expression compile cache.
_RE_CACHE = {}

# Hold the keylets.
UZBLS = {}

# Simple key names map.
_SIMPLEKEYS = {
  'Control': 'Ctrl',
  'ISO_Left_Tab': 'Shift-Tab',
  'space':'Space',
}

# Keycmd format which includes the markup for the cursor.
KEYCMD_FORMAT = "%s<span @cursor_style>%s</span>%s"


def escape(str):
    '''Prevent outgoing keycmd values from expanding inside the
    status_format.'''

    if not str:
        return ''

    for char in ['\\', '@']:
        if char in str:
            str = str.replace(char, '\\'+char)

    return "@[%s]@" % str


def get_regex(regex):
    '''Compiling regular expressions is a very time consuming so return a
    pre-compiled regex match object if possible.'''

    if regex not in _RE_CACHE:
        _RE_CACHE[regex] = re.compile(regex).match

    return _RE_CACHE[regex]


class Keylet(object):
    '''Small per-instance object that tracks all the keys held and characters
    typed.'''

    def __init__(self):
        self.cmd = ''
        self.cursor = 0
        self.held = []

        # to_string() string building cache.
        self._to_string = None

        self.modcmd = False

    def mod_held(self):
        ''' returns true if any modkey is held. '''
        return any([len(x) != 1 for x in self.held])

    def key_cmd(self):
        ''' get the keycmd-part of the keylet. '''
        return self.cmd

    def mod_cmd(self):
        ''' get the modcmd-part of the keylet. '''
        return ''.join(['<%s>' % key for key in self.held])

    def __repr__(self):
        return '<Keycmd(%r)>' % self.to_string()

    def to_string(self):
        '''Return a string representation of the keys held and pressed that
        have been recorded.'''

        if self._to_string is not None:
            # Return cached keycmd string.
            return self._to_string
        
        self._to_string = self.mod_cmd() + self.key_cmd()
        return self._to_string


    def match(self, regex):
        '''See if the keycmd string matches the given regex.'''

        return bool(get_regex(regex)(self.to_string()))


def make_simple(key):
    '''Make some obscure names for some keys friendlier.'''

    # Remove left-right discrimination.
    if key.endswith('_L') or key.endswith('_R'):
        key = key[:-2]

    if key in _SIMPLEKEYS:
        key = _SIMPLEKEYS[key]

    return key


def add_instance(uzbl, *args):
    '''Create the Keylet object for this uzbl instance.'''

    UZBLS[uzbl] = Keylet()


def del_instance(uzbl, *args):
    '''Delete the Keylet object for this uzbl instance.'''

    if uzbl in UZBLS:
        del UZBLS[uzbl]


def get_keylet(uzbl):
    '''Return the corresponding keylet for this uzbl instance.'''

    # Startup events are not correctly captured and sent over the uzbl socket
    # yet so this line is needed because the INSTANCE_START event is lost.
    if uzbl not in UZBLS:
        add_instance(uzbl)

    keylet = UZBLS[uzbl]
    keylet._to_string = None
    return keylet


def clear_keycmd(uzbl):
    '''Clear the keycmd for this uzbl instance.'''

    k = get_keylet(uzbl)
    k.cmd = ''
    k.cursor = 0
    k._to_string = None

    k.modcmd = k.mod_held()
    config = uzbl.get_config()
    if 'keycmd' not in config or config['keycmd'] != '':
        config['keycmd'] = ''

    uzbl.event('KEYCMD_CLEAR')


def update_event(uzbl, k, execute=True):
    '''Raise keycmd & modcmd update events.'''

    config = uzbl.get_config()
    if k.modcmd:
        keycmd = k.to_string()
        if execute:
            uzbl.event('MODCMD_UPDATE', k)
        if keycmd != k.to_string():
            return

        if 'modcmd_updates' in config and config['modcmd_updates'] != '1':
            return

        return uzbl.set('keycmd', escape(keycmd))

    if 'keycmd_events' in config and config['keycmd_events'] != '1':
        return

    keycmd = k.cmd
    if execute:
        uzbl.event('KEYCMD_UPDATE', k)
    if keycmd != k.cmd:
        return

    if not k.cmd:
        return uzbl.set('keycmd', '')

    # Generate the pango markup for the cursor in the keycmd.
    if k.cursor < len(k.cmd):
        cursor = k.cmd[k.cursor]

    else:
        cursor = ' '

    chunks = map(escape, [k.cmd[:k.cursor], cursor, k.cmd[k.cursor+1:]])
    uzbl.set('keycmd', KEYCMD_FORMAT % tuple(chunks))


def key_press(uzbl, key):
    '''Handle KEY_PRESS events. Things done by this function include:

    1. Ignore all shift key presses (shift can be detected by capital chars)
    3. In non-modcmd mode:
         a. append char to keycmd
    4. If not in modcmd mode and a modkey was pressed set modcmd mode.
    5. If in modcmd mode the pressed key is added to the held keys list.
    6. Keycmd is updated and events raised if anything is changed.'''

    if key.startswith('Shift_'):
        return

    if len(key) > 1:
        key = make_simple(key)

    k = get_keylet(uzbl)
    cmdmod = False

    if k.cmd and not k.modcmd and key == 'Space':
        k.cmd = "%s %s" % (k.cmd[:k.cursor], k.cmd[k.cursor:])
        k.cursor += 1
        cmdmod = True

    elif len(key) > 1:
        k.modcmd = True
        cmdmod = True

    elif not k.modcmd:
        config = uzbl.get_config()
        if 'keycmd_events' not in config or config['keycmd_events'] == '1':
            if len(key) == 1:
                cmdmod = True
                k.cmd = "%s%s%s" % (k.cmd[:k.cursor], key, k.cmd[k.cursor:])
                k.cursor += 1

        elif k.cmd:
            cmdmod = True
            k.cmd = ''
            k.cursor = 0

    if k.modcmd:
        if key == 'Shift-Tab' and 'Tab' in k.held:
            k.held.remove('Tab')

        if key not in k.held:
            k.held.append(key)
            k.held.sort()
            cmdmod = True

    if cmdmod:
        update_event(uzbl, k)


def key_release(uzbl, key):
    '''Respond to KEY_RELEASE event. Things done by this function include:

    1. Remove the key from the keylet held list.
    2. If in a mod-command then raise a MODCMD_EXEC.
    3. Check if any modkey is held, if so set modcmd mode.
    4. Update the keycmd uzbl variable if anything changed.'''

    if len(key) > 1:
        key = make_simple(key)

    k = get_keylet(uzbl)

    cmdmod = False
    if key in ['Shift', 'Tab'] and 'Shift-Tab' in k.held:
        key = 'Shift-Tab'

    elif key in ['Shift', 'Alt'] and 'Meta' in k.held:
        key = 'Meta'

    if key in k.held:
        cmdmod = True
        k.held.remove(key)
        k.modcmd = k.mod_held()
        if k.modcmd:
            uzbl.event('MODCMD_EXEC', k)

    if cmdmod:
       update_event(uzbl, k)


def set_keycmd(uzbl, keycmd):
    '''Allow setting of the keycmd externally.'''

    k = get_keylet(uzbl)
    k.modcmd = False
    k._to_string = None
    k.cmd = keycmd
    k.cursor = len(keycmd)

    update_event(uzbl, k, False)


def keycmd_strip_word(uzbl, sep):
    ''' Removes the last word from the keycmd, similar to readline ^W '''
    sep = sep or ' '
    k = get_keylet(uzbl)
    if not k.cmd:
        return

    cmd = k.cmd[:k.cursor]
    tail = len(k.cmd) - k.cursor

    if sep in cmd:
        tmp = cmd.rstrip(sep).rsplit(sep, 1)
    else:
        tmp = ('',)

    k.cmd = tmp[0] + (sep if len(tmp) == 2 else '') + k.cmd[k.cursor:]
    k.cursor = len(tmp[0]) + (len(tmp) - 1)

    assert len(k.cmd) - k.cursor == tail, "tail size changed (%s) (%s - %s)" % (tail, len(k.cmd), k.cursor)

    update_event(uzbl, k, False)


def keycmd_backspace(uzbl, _foo):
    ''' Removes the last char of the keycmd '''
    k = get_keylet(uzbl)
    if not k.cmd:
        return

    k.cmd = k.cmd[:k.cursor-1] + k.cmd[k.cursor:]
    k.cursor -= 1

    update_event(uzbl, k, False)


def keycmd_exec_current(uzbl, _foo):
    ''' Raise a KEYCMD_EXEC with the current keylet and then clear the keycmd '''
    k = get_keylet(uzbl)
    uzbl.event('KEYCMD_EXEC', k)
    clear_keycmd(uzbl)


def set_cursor_pos(uzbl, index):
    '''Allow setting of the cursor position externally. Supports negative
    indexing and relative stepping with '+' and '-'.'''

    k = get_keylet(uzbl)

    if index == '-':
        cursor = k.cursor - 1
    elif index == '+':
        cursor = k.cursor + 1
    else:
        cursor = int(index.strip())
        if cursor < 0:
            cursor = len(k.cmd) + cursor + 1

    if cursor < 0:
        cursor = 0

    if cursor > len(k.cmd):
        cursor = len(k.cmd)

    k.cursor = cursor
    update_event(uzbl, k, False)


def init(uzbl):
    '''Connect handlers to uzbl events.'''

    connects = {'INSTANCE_START': add_instance,
      'INSTANCE_EXIT': del_instance,
      'KEY_PRESS': key_press,
      'KEY_RELEASE': key_release,
      'SET_KEYCMD': set_keycmd,
      'KEYCMD_STRIP_WORD': keycmd_strip_word,
      'KEYCMD_BACKSPACE': keycmd_backspace,
      'KEYCMD_EXEC_CURRENT': keycmd_exec_current,
      'SET_CURSOR_POS': set_cursor_pos}

    uzbl.connect_dict(connects)
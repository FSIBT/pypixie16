"""
Usage:
   create_variable_list <filename>

Created variables.py which is used by the module to figure out where
in memory different settings are located.

"""

import docopt

commands = docopt.docopt(__doc__)

filename = commands["<filename>"]

with open(filename, "r") as f:
    lines = f.readlines()

values = {}
last_idx = None
for l in lines:
    a, b = l.strip().split()
    # need the ,0 to be convert from hex to int
    a = int(a, 0) - 0x4A000
    values[b] = a
    if last_idx:
        start = values[last_idx]
        values[last_idx] = [start, a - start]
    last_idx = b
if last_idx:
    start = values[last_idx]
    values[last_idx] = [start, 16]

with open("variables.py", "w") as f:
    f.write(
        '# automatically created by running "create_variable_list.py Pixie16DSP_revfgeneral_14b500m_r35207.var"\n'
    )
    f.write("# do not modify manually unless you know what you are doing ;)\n\n")

    f.write("settings = {\n")
    for k, v in values.items():
        f.write(f'          "{k}": [{v[0]}, {v[1]}],\n')
    f.write("        }\n")

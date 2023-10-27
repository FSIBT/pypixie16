import itertools

import numpy as np
from rich import print


from .settings_class import Settings


def compare_dict(A, B, key_string):
    """Deep ompare two dictionarys.

    Return a list of key and values that are different, e.g.
    [...,
     ["a/b/c/", valueA, valueB],
     ...
    ]

    """
    all_keys = set(A.keys()) | set(B.keys())

    output = []

    for key in all_keys:
        new_key_string = f"{key_string}/{key}"
        valueA = A.get(key)
        valueB = B.get(key)
        if isinstance(valueA, dict) and isinstance(valueB, dict):
            output += compare_dict(A[key], B[key], new_key_string)
        elif isinstance(valueA, list) and isinstance(valueB, list):
            output += compare_list(A[key], B[key], new_key_string)
        elif isinstance(valueA, (str, int, float)) and isinstance(
            valueB, (str, int, float)
        ):
            if valueA == valueB:
                pass
            else:
                output.append([new_key_string, valueA, valueB])
        else:
            print(
                f"[orange3]Warning[/] Unkown data types {type(valueA)} {type(valueB)}"
            )
    return output


def compare_list(A, B, key_string):
    """Deep ompare two lists.

    Return a list of key and values that are different, e.g.
    [...,
     ["a/b/c/", valueA, valueB],
     ...
    ]

    """

    output = []

    for i, (valueA, valueB) in enumerate(itertools.zip_longest(A, B)):
        new_key_string = f"{key_string}[{i}]"
        if isinstance(valueA, dict) and isinstance(valueB, dict):
            output += compare_dict(valueA, valueB, new_key_string)
        elif isinstance(valueA, list) and isinstance(valueB, list):
            output += compare_list(valueA, valueB, new_key_string)
        elif isinstance(valueA, (str, int, float)) and isinstance(
            valueB, (str, int, float)
        ):
            if valueA == valueB:
                pass
            else:
                output.append([new_key_string, valueA, valueB])
        else:
            print(
                f"[orange3]Warning[/] Unkown data types {type(valueA)} {type(valueB)}"
            )
    return output


def compare_module_setting(A, B, quiet=False, channels=None):
    """Compare the settings of two modules (for the new json based settings)

    Print the difference.

    If quiet is True, then just return True/False depending if they differ or not.

    The functions assumes that both settings have the same structure.
    """

    if not isinstance(A, Settings):
        print(
            "[red]ERROR[/] compare_module_setting: The first Setting is not a Settings object."
        )
        return None

    if not isinstance(B, Settings):
        print(
            "[red]ERROR[/] compare_module_setting: The second Setting is not a Settings object."
        )
        return None

    output = compare_dict(A, B, "")

    if channels is None:
        channels = list(range(16))

    if not quiet:
        print("Comparing settings:")
        print(f"  a: {A.filename.name}")
        print(f"  b: {B.filename.name}")
        print("")
        if output:
            keylen = max(len(k[0]) for k in output)
            print(f"{'settting':<{keylen}} {'a':>10} {'b':>10}")
            for a, b, c in output:
                skip = True
                for c in channels:
                    if f"[{c}]" in a:
                        skip = False
                        break
                if not skip:
                    print(f"{a:<{keylen}} {b:>10} {c:>10}")
        else:
            print("Settings are identical")

    else:
        return len(output) > 0

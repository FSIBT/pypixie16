def compare_module_setting(
    A, B, quiet=False, writeable_only=True, units=True, channels=None
):
    """Compare the settings of two modules

    Print the difference.

    If quiet is True, then just return True/False

    The functions assumes that both settings have the same structure.
    """

    if type(A) != type(B):
        print(f"compare_module_setting: both items need to have the same type")
        return None

    if type(A) != Settings:
        print(f"compare_module_setting: both items need to be Setting classes")
        return None

    if not quiet:
        print("Comparing settings:")
        print(f"  a: {A.filename}")
        print(f"  b: {B.filename}")
        print("")

        if writeable_only:
            keys = [k for k in settings.keys() if settings[k][0] < 832]
        else:
            keys = list(settings.keys())

        if units:
            keys = keys + Settings.derived_keys
            keys = [k for k in keys if k not in Settings.derived_from_keys]

        for k in keys:
            if units:
                valueA = A.units[k]
                valueB = B.units[k]
            else:
                valueA = A[k]
                valueB = B[k]
            if isinstance(valueA, (int, str, float)):
                if valueA != valueB:
                    print(f"{k} differs:\n     a: {valueA}\n     b: {valueB}")
            elif isinstance(valueA, (list, tuple)):
                first = True
                for i, (a, b) in enumerate(zip(valueA, valueB)):
                    if channels:
                        if i not in channels:
                            continue
                    if a != b:
                        if first:
                            print(f"{k} differs:")
                            first = False
                        # if these are bit values, only show bits that are different
                        if isinstance(a, str) and "-" in a:
                            aa = a.split("-")
                            bb = b.split("-")
                            for x, y in zip(aa, bb):
                                if x != y:
                                    print(f"  ch:{i}\n     a: {x}\n     b: {y}")
                        else:
                            print(f"  ch:{i}\n     a: {a}\n     b: {b}")
            else:
                print("This shouldn't happen. type value A", type(valueA))

    # convert to a sorted json string to make deep comparison possible
    if writeable_only:
        return json.dumps(A.rawdata[:832], sort_keys=True) == json.dumps(
            B.rawdata[:832], sort_keys=True
        )
    else:
        return json.dumps(A.rawdata, sort_keys=True) == json.dumps(
            B.rawdata, sort_keys=True
        )

def read_mca_mode_data(filename):
    """Read MCA data files: 32k 32bit words for 16 channels"""

    results = {}
    with open(filename, "rb") as f:
        for channel in range(16):
            spectrum = []
            for i in range(32 * 1024):
                spectrum.append(int.from_bytes(f.read(4), byteorder="little"))
            spectrum = np.array(spectrum)
            results[channel] = spectrum
    return results

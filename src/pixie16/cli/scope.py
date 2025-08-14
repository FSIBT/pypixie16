"""
Pixie16 Scope - Real-time visualization and parameter control for PIXIE-16 modules

Usage:
  pixie16-scope [--dummy] [--module <N>] [--channels <list>]

Options:
  --dummy           Use dummy data for testing without hardware
  --module <N>      Specify module number [default: 2]
  --channels <list> Specify channels to display [default: 0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15]
"""

from docopt import docopt

commands = docopt(__doc__)


def main():
    import argparse
    import sys
    import traceback

    from pixie16.ui import PixieScopeApp, QApplication

    parser = argparse.ArgumentParser(description="PixieScope")
    parser.add_argument("--dummy", action="store_true", help="Run in dummy mode")
    parser.add_argument(
        "--slot", type=int, default=2, help="Physical slot number in PXI crate"
    )
    parser.add_argument(
        "--channels",
        type=str,
        default="0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15",
        help="Comma-separated channel list",
    )

    args = parser.parse_args()

    # Parse channels
    try:
        channels = [int(ch.strip()) for ch in args.channels.split(",")]
    except ValueError:
        print("Error: Invalid channel list format")
        sys.exit(1)

    # Create QApplication
    app = QApplication(sys.argv)
    app.setApplicationName("PIXIE-16 Scope")

    def exception_hook(exctype, value, traceback_obj):
        print(f"Unhandled exception: {exctype.__name__}: {value}")

        traceback.print_exception(exctype, value, traceback_obj)

    sys.excepthook = exception_hook

    # Print startup info
    if args.dummy:
        print("Starting PIXIE-16 Scope in DUMMY MODE")
        print(f"  - Will simulate PIXIE-16 in slot {args.slot}")
    else:
        print("Starting PIXIE-16 Scope with REAL HARDWARE")
        print(f"  - Physical slot: {args.slot}")
        print(f"  - Channels: {channels}")

    window = None
    try:
        window = PixieScopeApp(
            dummy_mode=args.dummy, physical_slot=args.slot, channels=channels
        )
        window.show()

        print("\n" + "=" * 60)
        print("PIXIE-16 Scope is ready!")
        print("Usage:")
        print("  - Select mode: MCA, List, or Traces")
        print("  - Click Start to begin acquisition")
        print("  - Use parameter controls to adjust settings")
        print("  - Click Stop to end acquisition")
        print("=" * 60 + "\n")

        # Run the application
        exit_code = app.exec()

        print("Application exited cleanly")
        sys.exit(exit_code)

    except KeyboardInterrupt:
        print("\nKeyboard interrupt received...")
        if window:
            window.manual_shutdown()
        sys.exit(0)

    except Exception as e:
        print(f"Fatal error: {e}")
        traceback.print_exc()

        if window:
            try:
                window.manual_shutdown()
            except:
                pass
        sys.exit(1)


if __name__ == "__main__":
    main()

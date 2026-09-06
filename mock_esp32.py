
import os
import sys


def _reexec_into_venv() -> None:
    try:
        import numpy 
        import sounddevice  

        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "daemon"))
        return
    except ImportError:
        pass
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    venv_python = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "bin", "python")
    if not in_venv and os.path.exists(venv_python):
        os.execv(venv_python, [venv_python, os.path.abspath(__file__), *sys.argv[1:]])
    print("missing deps — pip install -e './daemon[audio]' inside ~/desk-secretary/.venv",
          file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    _reexec_into_venv()
    from deskd.satellite import main

    main()

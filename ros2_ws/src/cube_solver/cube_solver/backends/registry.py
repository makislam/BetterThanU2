from .kociemba_backend import KociembaBackend

_BACKENDS = {
    "kociemba": KociembaBackend,
    # "korf": KorfBackend,  # add here when implemented — no other changes needed
}


def get_backend(name):
    try:
        backend_cls = _BACKENDS[name]
    except KeyError:
        raise ValueError(f"Unknown solver algorithm '{name}'. Available: {list(_BACKENDS)}")
    return backend_cls()

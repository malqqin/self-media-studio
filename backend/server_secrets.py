"""Server-side encryption for deployment credentials. Back up this key separately."""
from cryptography.fernet import Fernet
from . import config


def cipher():
    path = config.DATA/'server-secret.key'
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('xb') as f:
            f.write(Fernet.generate_key())
        path.chmod(0o600)
    except FileExistsError:
        pass
    return Fernet(path.read_bytes())


def encrypt(value):
    return cipher().encrypt(value.encode()).decode()


def decrypt(value):
    return cipher().decrypt(value.encode()).decode() if value else ''

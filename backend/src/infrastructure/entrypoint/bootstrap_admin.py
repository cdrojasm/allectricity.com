"""Interactive bootstrap; no default password or public bootstrap endpoint."""

from getpass import getpass
from pydantic import EmailStr, TypeAdapter
from src.infrastructure.security.container import build_services
from src.infrastructure.security.settings import Settings


def main():
    email = str(
        TypeAdapter(EmailStr).validate_python(input("Admin email: ").strip())
    ).lower()
    name = input("First name: ").strip() or "Administrator"
    password = getpass("Password (12–128 characters): ")
    if not 12 <= len(password) <= 128 or password != getpass("Confirm password: "):
        raise SystemExit("Invalid password or confirmation")
    services = build_services(Settings.from_env())
    try:
        user = services.admin.bootstrap(email, password, name[:100])
        print("Super administrator created:", user["id"])
    finally:
        services.store.engine.dispose()


if __name__ == "__main__":
    main()

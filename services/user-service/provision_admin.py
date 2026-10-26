"""Promote a pre-registered account to the first ADMIN using local DB access."""

import argparse
import getpass

from database import get_connection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email", help="email of the already-registered account")
    args = parser.parse_args()

    confirmation = getpass.getpass(f"Type PROMOTE {args.email} to continue: ")
    if confirmation != f"PROMOTE {args.email}":
        parser.error("confirmation did not match; no account was changed")

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended('nexora-initial-admin', 0));"
            )
            cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'ADMIN';")
            if cursor.fetchone()[0]:
                parser.error("an ADMIN already exists; use an authorized database administration process")

            cursor.execute(
                """
                UPDATE users
                SET role = 'ADMIN'
                WHERE email = %s AND role = 'CUSTOMER'
                RETURNING id, username, email;
                """,
                (args.email,),
            )
            account = cursor.fetchone()
            if account is None:
                parser.error("no CUSTOMER account matched that email; no account was changed")

    print(f"Promoted account {account[1]} ({account[2]}) to ADMIN.")


if __name__ == "__main__":
    main()

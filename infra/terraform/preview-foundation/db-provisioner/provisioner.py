import os

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from db_names import (
    InvalidProvisioningRequest,
    validate_database_name,
    validate_role_memberships,
)


APP_USER = "haunted_halls_preview_app"
PROVISIONER_USER = "haunted_halls_preview_provisioner"
PROTECTED_DATABASES = frozenset({"haunted_halls", "haunted_halls_staging"})


def connect(database_name: str | None = None) -> psycopg.Connection:
    return psycopg.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=database_name or os.environ.get("DB_NAME", "postgres"),
        user=os.environ.get("DB_USER", PROVISIONER_USER),
        password=os.environ["DB_PASSWORD"],
        autocommit=True,
        connect_timeout=10,
        row_factory=dict_row,
    )


def provision(operation: str, database_name: str) -> dict[str, object]:
    database_name = validate_database_name(database_name)
    if database_name in PROTECTED_DATABASES:
        raise InvalidProvisioningRequest("protected database names are not allowed")
    if operation not in {"create", "drop"}:
        raise InvalidProvisioningRequest("operation must be create or drop")

    with connect() as connection:
        assert_database_roles_hardened(connection)

    if operation == "create":
        return create_preview_database(database_name)
    return drop_preview_database(database_name)


def assert_database_roles_hardened(connection: psycopg.Connection) -> None:
    rows = connection.execute(
        """
        SELECT rolname, rolcanlogin, rolsuper, rolcreaterole, rolcreatedb, rolinherit,
               COALESCE(pg_has_role(oid, to_regrole('cloudsqlsuperuser'), 'MEMBER'), false)
                   AS cloudsqlsuperuser_member,
               COALESCE(pg_has_role(oid, to_regrole('haunted_halls_app'), 'MEMBER'), false)
                   AS production_role_member,
               COALESCE(pg_has_role(oid, to_regrole('haunted_halls_staging_app'), 'MEMBER'), false)
                   AS staging_role_member,
               has_database_privilege(rolname, 'haunted_halls', 'CONNECT')
                   AS production_connect,
               has_database_privilege(rolname, 'haunted_halls_staging', 'CONNECT')
                   AS staging_connect
        FROM pg_roles
        WHERE rolname IN (%s, %s)
        """,
        (APP_USER, PROVISIONER_USER),
    ).fetchall()
    roles = {row["rolname"]: row for row in rows}
    app_role = roles.get(APP_USER)
    provisioner_role = roles.get(PROVISIONER_USER)

    if app_role is None or provisioner_role is None:
        raise RuntimeError("preview database roles are not provisioned")

    membership_rows = connection.execute(
        """
        SELECT member_role.rolname AS member_name, granted_role.rolname AS granted_role_name
        FROM pg_auth_members AS membership
        JOIN pg_roles AS member_role ON member_role.oid = membership.member
        JOIN pg_roles AS granted_role ON granted_role.oid = membership.roleid
        WHERE member_role.rolname IN (%s, %s)
        """,
        (APP_USER, PROVISIONER_USER),
    ).fetchall()
    memberships = {APP_USER: set(), PROVISIONER_USER: set()}
    for row in membership_rows:
        memberships[row["member_name"]].add(row["granted_role_name"])
    try:
        validate_role_memberships(memberships)
    except ValueError as error:
        raise RuntimeError("preview database role memberships are not hardened") from error

    for role in (app_role, provisioner_role):
        if (
            not role["rolcanlogin"]
            or role["rolsuper"]
            or role["rolcreaterole"]
            or role["cloudsqlsuperuser_member"]
            or role["production_role_member"]
            or role["staging_role_member"]
            or role["production_connect"]
            or role["staging_connect"]
        ):
            raise RuntimeError("preview database role hardening is incomplete")

    if app_role["rolcreatedb"] or provisioner_role["rolinherit"]:
        raise RuntimeError("preview database role attributes are not hardened")
    if not provisioner_role["rolcreatedb"]:
        raise RuntimeError("preview provisioner does not have its narrowly scoped role grant")


def create_preview_database(database_name: str) -> dict[str, object]:
    with connect() as connection:
        existing = connection.execute(
            """
            SELECT pg_get_userbyid(datdba) AS owner
            FROM pg_database
            WHERE datname = %s
            """,
            (database_name,),
        ).fetchone()

        if existing is None:
            connection.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(database_name),
                    sql.Identifier(APP_USER),
                )
            )
            created = True
        elif existing["owner"] != APP_USER:
            raise RuntimeError("existing preview database has an unexpected owner")
        else:
            created = False

        connection.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(APP_USER)))
        connection.execute(
            sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(
                sql.Identifier(database_name)
            )
        )
        connection.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, {}").format(
                sql.Identifier(database_name),
                sql.Identifier(APP_USER),
                sql.Identifier(PROVISIONER_USER),
            )
        )
        connection.execute("RESET ROLE")

    with connect(database_name) as connection:
        connection.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(APP_USER)))
        connection.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
        connection.execute(
            sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(
                sql.Identifier(APP_USER)
            )
        )
        connection.execute("RESET ROLE")

    return {"database": database_name, "created": created, "operation": "create"}


def drop_preview_database(database_name: str) -> dict[str, object]:
    with connect() as connection:
        existing = connection.execute(
            """
            SELECT pg_get_userbyid(datdba) AS owner
            FROM pg_database
            WHERE datname = %s
            """,
            (database_name,),
        ).fetchone()
        if existing is None:
            return {"database": database_name, "dropped": False, "operation": "drop"}
        if existing["owner"] != APP_USER:
            raise RuntimeError("refusing to drop a database not owned by the preview app")

        connection.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(APP_USER)))
        connection.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = %s AND pid <> pg_backend_pid()
            """,
            (database_name,),
        )
        connection.execute(
            sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name))
        )
        connection.execute("RESET ROLE")

    return {"database": database_name, "dropped": True, "operation": "drop"}

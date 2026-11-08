# Store loans in a TOML file

Decision: Loans are stored in one TOML file, because people can read and fix it by hand.

Rejected: SQLite, because a broken database is hard to repair without the tool.

from contextlib import contextmanager


class TransactionManager:
    def __init__(self, connection, checkpoint=None):
        self.connection = connection
        self.callback = checkpoint
        self.serial = 0

    @contextmanager
    def atomic(self):
        nested = self.connection.in_transaction
        self.serial += 1
        name = f"evidence_sp_{self.serial}"
        self.connection.execute(f"SAVEPOINT {name}" if nested else "BEGIN IMMEDIATE")
        try:
            yield
            self.connection.execute(f"RELEASE SAVEPOINT {name}" if nested else "COMMIT")
        except BaseException:
            if self.connection.in_transaction:
                if nested:
                    self.connection.execute(f"ROLLBACK TO SAVEPOINT {name}")
                    self.connection.execute(f"RELEASE SAVEPOINT {name}")
                else:
                    self.connection.execute("ROLLBACK")
            raise

    def checkpoint(self, name):
        if self.callback is not None:
            self.callback(name)

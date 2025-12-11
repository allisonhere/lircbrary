from rq import Connection, Worker

from app.config import get_settings
from app.tasks import get_queue


def main() -> None:
    settings = get_settings()
    queue = get_queue()
    with Connection(queue.connection):
        worker = Worker([settings.queue_name])
        worker.work()


if __name__ == "__main__":
    main()

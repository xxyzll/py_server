import string
import threading
import queue

# queue是线程安全的
class Log:
    def __init__(self, file_name=None) -> None:
        self.lock = threading.Lock()
        self.work_q = queue.Queue()

    def run(self):
        while(1):
            s = self.work_q.get()
            print(s)

    def add_out(self, str: string):
        self.work_q.put(str)
     


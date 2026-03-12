import time

def run_worker():
    print("AgentX Worker Started")

    while True:
        print("Worker running...")
        time.sleep(5)

if __name__ == "__main__":
    run_worker()

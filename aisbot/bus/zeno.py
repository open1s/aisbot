import zenoh
import time
import threading


i = 0


def read_temp():
    global i
    i = i + 1
    return i


ri = 1


def listener(sample):
    global ri
    payload = int(sample.payload.to_string())
    if ri != payload:
        print(f"Error: Expected {ri}, got {payload}")
    ri = ri + 1
    print(
        f"Received {sample.kind} ('{sample.key_expr}': '{sample.payload.to_string()}')"
    )


if __name__ == "__main__":
    # Start thread for subscriber

    def subscriber():
        with zenoh.open(zenoh.Config()) as session:
            session.declare_subscriber("myhome/kitchen/temp", listener)
            time.sleep(60)

    threading.Thread(target=subscriber).start()

    time.sleep(1)

    with zenoh.open(zenoh.Config()) as session:
        key = "myhome/kitchen/temp"
        pub = session.declare_publisher(key)
        while True:
            t = read_temp()
            buf = f"{t}"
            print(f"Putting Data ('{key}': '{buf}')...")
            pub.put(buf)
            time.sleep(0.00001)

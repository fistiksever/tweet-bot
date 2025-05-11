from flask import Flask
from threading import Thread

app = Flask('')


@app.route('/')
def home():
    return "Bot aktif"


def run():
    app.run(host='0.0.0.0', port=8080)


def keep_alive():
    t = Thread(target=run)
    t.start()


from keep_alive import keep_alive

if __name__ == "__main__":
    keep_alive()
    main()

import pixie16


if __name__ == "__main__":
    pipe = pixie16.pipeline.Pipeline()
    pipe.connect(["DummyData", "GatherEvents", "PrintData"])
    pipe.configure({"size": 2})
    pipe.start()

    while True:
        pipe.poll()

        if pipe.status == pixie16.pipeline.Status.WAITING:
            break

        if pipe.status == pixie16.pipeline.Status.PANICKING:
            assert False

    pipe.quit()

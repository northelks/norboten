import hashlib
import os


def check(ctx):
    data = "/var/lib/app/data"
    orders = os.path.join(data, "orders.db")
    try:
        with open(orders, "rb") as f:
            head = hashlib.sha256(f.read(1 << 20)).hexdigest()
        size = os.path.getsize(orders)
        customers = os.path.getsize(os.path.join(data, "customers.db"))
    except OSError as e:
        return ctx.failed("The application's data is not all there.", str(e))
    if (size, head, customers) != (
        ctx.state["orders_size"],
        ctx.state["orders_head"],
        ctx.state["customers_size"],
    ):
        return ctx.failed("The application's data was changed, truncated or replaced.")
    st = os.statvfs("/var/lib/app")
    free = st.f_bavail / st.f_blocks
    pvs = ctx.run(["pvs", "--noheadings", "-o", "pv_name,vg_name"]).out
    evidence = ctx.run(["df", "-h", "/var/lib/app"]).out + "\n" + pvs
    if free < 0.30:
        return ctx.failed(f"/var/lib/app has only {free:.0%} free.", evidence)
    return ctx.passed(f"/var/lib/app has {free:.0%} free and its data is intact.", evidence)

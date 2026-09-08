"""Explicit exchange-shaped evidence for deterministic execution tests."""


def exit_order(order_id=121, client_id="TP-A", list_id=120, kind="LIMIT_MAKER", qty="0.1"):
    return dict(symbol="SOLUSDT", orderId=order_id, clientOrderId=client_id,
                orderListId=list_id, side="SELL", type=kind, status="FILLED",
                origQty=qty, executedQty=qty)


def order_list(list_id, client_id, legs, status="EXEC_STARTED", kind="OCO"):
    return dict(symbol="SOLUSDT", orderListId=list_id, listClientOrderId=client_id,
                contingencyType=kind, listStatusType=status,
                orders=[{key: leg[key] for key in ("symbol", "orderId", "clientOrderId")}
                        for leg in legs])

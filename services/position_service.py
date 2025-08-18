from db.db_session import SessionLocal
from db.models import Position
from datetime import datetime


def get_position(symbol: str) -> Position | None:
    """Fetches the current position for a given symbol."""
    session = SessionLocal()
    try:
        position = session.query(Position).filter_by(symbol=symbol).first()
        if position:
            print(f"[DB] Found existing position for {symbol}: qty={position.quantity}, avg_price={position.average_price}")
        else:
            print(f"[DB] No existing position for {symbol}.")
        return position
    except Exception as e:
        print(f"[DB ERROR] Failed to get position for {symbol}: {e}")
        return None
    finally:
        session.close()


def upsert_position(symbol: str, quantity: float, price: float, *, strict: bool = False, overwrite: bool = False) -> None:
    """
    Inserts or updates a trading position in the database.
    - If position exists → recalculates weighted average price (unless overwrite=True).
    - If not → inserts new position.
    - If position closes (quantity → 0), resets avg price to 0.
    - Optional: strict mode will raise if invalid input is detected.
    - overwrite=True means replace quantity & price exactly (used for reconciliation).
    """
    session = SessionLocal()
    try:
        position = session.query(Position).filter_by(symbol=symbol).first()
        now = datetime.utcnow()

        quantity = round(quantity, 4)
        price = round(price, 4)

        # Allow quantity=0 for reconciliation
        if position:
            if overwrite:
                position.quantity = quantity
                position.average_price = 0.0 if quantity == 0 else price
            else:
                if quantity == 0:
                    print(f"[DB] Closing position for {symbol} → all shares sold.")
                    position.quantity = 0
                    position.average_price = 0.0
                else:
                    # Weighted average update
                    new_total_qty = position.quantity + quantity
                    new_total_cost = position.average_price * position.quantity + price * quantity

                    if new_total_qty == 0:
                        position.quantity = 0
                        position.average_price = 0.0
                    else:
                        position.quantity = new_total_qty
                        position.average_price = new_total_cost / new_total_qty

            position.updated_at = now
        else:
            position = Position(
                symbol=symbol,
                quantity=quantity,
                average_price=0.0 if quantity == 0 else price,
                updated_at=now
            )
            session.add(position)

        session.commit()
        print(f"[DB] upsert_position → {symbol}: qty={position.quantity}, avg_price={position.average_price:.2f}")

    except Exception as e:
        session.rollback()
        print(f"[DB ERROR] Failed to upsert position for {symbol}: {e}")
        if strict:
            raise
    finally:
        session.close()

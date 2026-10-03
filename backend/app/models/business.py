import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import UUID, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class OrderStatus:
    ACTIVE = "active"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class PaymentStatus:
    PENDING = "pending"
    PAID = "paid"
    REFUNDING = "refunding"
    REFUNDED = "refunded"


class ShipmentStatus:
    PENDING = "pending"
    SHIPPED = "shipped"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    EXCEPTION = "exception"


class AfterSalesRequestStatus:
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    RETURNING = "returning"
    RECEIVED = "received"
    REFUNDED = "refunded"
    CLOSED = "closed"


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255))

    orders = relationship("Order", back_populates="customer")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(100))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    supports_no_reason_return: Mapped[bool] = mapped_column(Boolean)

    order_items = relationship("OrderItem", back_populates="product")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"))
    status: Mapped[str] = mapped_column(String(20))
    payment_status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
    )

    customer = relationship("Customer", back_populates="orders")
    order_items = relationship("OrderItem", back_populates="order")
    shipments = relationship("Shipment", back_populates="order")
    after_sales_requests = relationship("AfterSalesRequest", back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    order = relationship("Order", back_populates="order_items")
    product = relationship("Product", back_populates="order_items")
    after_sales_requests = relationship("AfterSalesRequest", back_populates="order_item")


class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"))
    tracking_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20))
    # Supplied as the last meaningful logistics update, never a generic ORM onupdate.
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Actual delivery/signature time, stored as a UTC instant; pending shipments have none.
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    order = relationship("Order", back_populates="shipments")


class AfterSalesRequest(Base):
    __tablename__ = "after_sales_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"))
    order_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("order_items.id"))
    type: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
    )

    order = relationship("Order", back_populates="after_sales_requests")
    order_item = relationship("OrderItem", back_populates="after_sales_requests")

from uuid import UUID


# 当前以应用控制的 Demo Customer 作为 trusted Business Customer context；
# 它不是用户登录身份，也不代表已经实现 Production Authentication。
DEMO_CUSTOMER_ID = UUID("6e944fd5-2ff9-5ce5-8d83-c82006d21b2a")

# DAO-style exploit lessons
The DAO incident combined a recursive callback with balance accounting performed too late. Each callback withdrew against the unchanged balance, draining funds until gas or liquidity stopped the recursion. The durable lesson is to update effects before interactions and to keep external calls narrowly scoped.

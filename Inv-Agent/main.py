import asyncio
import os
from dataclasses import dataclass
from typing import Optional
from openai import AsyncOpenAI
from agents import Agent, OpenAIChatCompletionsModel, Runner, set_tracing_disabled, function_tool, ModelSettings, enable_verbose_stdout_logging
from pydantic import BaseModel
from dotenv import load_dotenv
import sqlite3

# enable_verbose_stdout_logging()

load_dotenv()

GEMINI_MODEL = "gemini/gemini-2.0-flash-exp"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not found!")

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DB_PATH = "inventory.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            quantity INTEGER NOT NULL
        )
    ''')
    conn.commit()
    conn.close()


client = AsyncOpenAI(
    api_key=GEMINI_API_KEY,
    base_url=GEMINI_BASE_URL
)

model = OpenAIChatCompletionsModel(
    model="gemini-2.0-flash",
    openai_client=client
)


@dataclass
class InventoryItemInput:
    operation: str
    id: int = None
    name: str = None
    quantity: int = None


class HelpfulAgentOutput(BaseModel):
    response_type: str
    inventory_data: str = None

# New inventory management tool


def fetch_inventory():
    """
    Fetch the current inventory from the database.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM inventory")
    rows = c.fetchall()
    conn.close()
    return rows


@function_tool
async def manageInventory(item: InventoryItemInput) -> str:
    """
    Manage inventory by adding, updating, or deleting items.
    Operations: 'add' (new item), 'update' (modify existing), 'delete' (remove item).
    For 'add', provide name and quantity. For 'update' or 'delete', provide id.
    """
    print(f"\nLOG: manageInventory tool is being called!")
    operation = item.operation.lower()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    try:
        if operation == "add":
            if not item.name or item.quantity is None:
                return "Error: Name and quantity are required for adding an item."
            c.execute("INSERT INTO inventory (name, quantity) VALUES (?, ?)",
                      (item.name, item.quantity))
            conn.commit()
            new_id = c.lastrowid
            return f"Added {item.name} with ID {new_id} and quantity {item.quantity}."

        elif operation == "update":
            if item.id is None or not item.name or item.quantity is None:
                return "Error: ID, name, and quantity are required for updating an item."
            c.execute("UPDATE inventory SET name = ?, quantity = ? WHERE id = ?",
                      (item.name, item.quantity, item.id))
            if c.rowcount == 0:
                return f"Error: Item with ID {item.id} not found."
            conn.commit()
            return f"Updated item ID {item.id} to {item.name} with quantity {item.quantity}."

        elif operation == "delete":
            if item.id is None:
                return "Error: ID is required for deleting an item."
            c.execute("DELETE FROM inventory WHERE id = ?", (item.id,))
            if c.rowcount == 0:
                return f"Error: Item with ID {item.id} not found."
            conn.commit()
            return f"Deleted item ID {item.id}."

        else:
            return "Error: Invalid operation. Use 'add', 'update', or 'delete'."

    except Exception as e:
        return f"Error: {str(e)}"

    finally:
        conn.close()

# Define the agent with both tools
agent = Agent(
    name="Helpful Assistant",
    instructions="""
    You are a helpful assistant for managing inventory.
    
    You have access to the `manageInventory` tool, which you must use to perform all inventory operations (add, update, delete).
    
    - To ADD a new item, use the `manageInventory` tool with the `operation` set to 'add', and provide the item's `name` and `quantity`. Do not provide an `id`.
    - To UPDATE an existing item, use the `manageInventory` tool with the `operation` set to 'update', and provide the `id`, along with the new `name` and `quantity`.
    - To DELETE an item, use the `manageInventory` tool with the `operation` set to 'delete', and provide the item's `id`.

    After successfully using the `manageInventory` tool, provide a summary of the action in the following format:
    "response_type": "<'is inventory' if manageInventory was called else 'not inventory'>",
    "inventory_data": "<your summary of what was done>"
    """,
    model=model,
    tools=[manageInventory],
    # output_type=HelpfulAgentOutput
)


async def main(kickOffMessage: str):
    print(f"RUN Initiated: {kickOffMessage}")

    result = await Runner.run(
        agent,
        input=kickOffMessage
    )
    # Print results for debugging
    print(result.final_output)

    if result.final_output and "is inventory" in result.final_output:
        print("\nCurrent Inventory:")
        rows = fetch_inventory()  # fetch from DB
        for row in rows:
            print(f"ID: {row[0]}, Name: {row[1]}, Quantity: {row[2]}")


def start():
    if not os.path.exists(DB_PATH):
        print(f"No database file found at '{DB_PATH}'. Initializing a new one.")
        init_db()
    else:
        print(f"Database file found at '{DB_PATH}'. Re-using existing inventory.")

    asyncio.run(main("del item in the inventory: id 2"))


if __name__ == "__main__":
    start()
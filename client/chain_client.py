from web3 import Web3
from eth_account import Account
import json
import logging
from locust import HttpUser, task, between
import numpy as np
import hashlib
from nacl.signing import SigningKey
import time
import json
from eth_account import Account
from eth_account._utils.legacy_transactions import serializable_unsigned_transaction_from_dict
from eth_utils import keccak, to_bytes, to_hex
from eth_keys import keys

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)

AMOUNT = 1

SEQUENCER_URL = "http://127.0.0.1:8000"

NODE_URL = "http://127.0.0.1:8545"
CONTRACT_ADDRESS = "0xe7f1725e7734ce288f8367e1bb143e90bb3f0512"


def hex_to_bytes(hex_str: str) -> bytes:
    if hex_str.startswith("0x"):
        hex_str = hex_str[2:]
    return bytes.fromhex(hex_str)

def bytes_to_hex(data: bytes) -> str:
    return "0x" + data.hex()

def load_contract_abi() -> dict:
    with open("Rollup.json", "r") as f:
        contract_json = json.load(f)
    return contract_json["abi"]

def load_layer_2_accounts():
    with open("funded_accounts.json", "r") as f:
        init_state = json.load(f)
    return init_state


LAYER_2_ACCOUNTS = load_layer_2_accounts()


def make_deposit_call(address : str, private_key : str, contract, web3):
    gas_estimate = contract.functions.depositETH(address).estimate_gas({
        "from": address,
        "value": web3.to_wei(1, "ether")
    })
    gas_price = web3.eth.gas_price
    tx = contract.functions.depositETH(address).build_transaction({
        "from": address,
        "value": web3.to_wei(1, "ether"),
        "gas": gas_estimate,
        "gasPrice": gas_price,
        "nonce": web3.eth.get_transaction_count(address)
    })
    logger.info("Transaction:", tx)
    signed_tx = web3.eth.account.sign_transaction(tx, private_key=private_key)
    tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)
    logger.info(f"Transaction hash: {tx_hash.hex()}")
    receipt = web3.eth.wait_for_transaction_receipt(tx_hash)
    logger.info("Transaction receipt:", receipt)
    time.sleep(1)
    
def add_users_to_the_rollup():
    web3 = Web3(Web3.HTTPProvider(NODE_URL))
    contract_address = web3.to_checksum_address(CONTRACT_ADDRESS)
    contract_abi = load_contract_abi()
    contract = web3.eth.contract(address=contract_address, abi=contract_abi)
    for acc in LAYER_2_ACCOUNTS:
        logger.info(acc)
        make_deposit_call(acc["pub_key"], private_key=acc["priv_key"], contract=contract, web3=web3)
    logger.info("successfully depsited all accounts")


def choose_random_transaction_pair(accounts: list[dict]) -> list[int]:
    indices = np.random.choice(len(accounts), size=2, replace=False)
    return indices.tolist()


def transaction_body_to_bytes(trans_body : dict) -> bytes:
        sender_bytes = hex_to_bytes(trans_body["sender"])
        receiver_bytes = hex_to_bytes(trans_body["receiver"])
        nonce_bytes = trans_body["nonce"].to_bytes(8, 'little') 
        amount_bytes = trans_body["amount"].to_bytes(8, 'little')
        msg = sender_bytes + receiver_bytes + nonce_bytes + amount_bytes
        return hashlib.sha256(msg).digest()


def create_transaction(sender : dict , receiver: dict, sender_idx : int, nonce: int) -> dict:
        
        trans_body = {
            "sender" : sender["pub_key"],
            "receiver" : receiver["pub_key"],
            "amount" : str(AMOUNT),
            "nonce": nonce,
        }
        private_key = keys.PrivateKey(hex_to_bytes(sender["priv_key"]))
        public_key = private_key.public_key
        message = json.dumps(trans_body, separators=(",", ":"), sort_keys=True)
        message_bytes = message.encode("utf-8")
        signature = private_key.sign_msg(message_bytes)

        trans_body["signature"] ={
           "pubKey": public_key.to_hex(),
            "signature": signature.to_hex()
        }
        logger.info(trans_body)
        return trans_body

def create_transaction_to_submit(nonce : int, a : int , b : int):
        sender = LAYER_2_ACCOUNTS[a]
        receiver = LAYER_2_ACCOUNTS[b]
        return create_transaction(sender, receiver, a, nonce)
    
class StefanJorisRollUpUser(HttpUser):
    host = SEQUENCER_URL
    wait_time = between(1, 1.5)
    #def on_start(self):
     #    add_users_to_the_rollup()

    @task
    def submit_transaction(self):
        a, b = choose_random_transaction_pair(LAYER_2_ACCOUNTS)
        res = self.client.post("/api/get-nonce", json={"account": LAYER_2_ACCOUNTS[a]["pub_key"]})
        if res.status_code != 200:
            print(f"Failed to get nonce: {res.text}")
            return

        try:
            nonce = res.json().get("nonce")
        except Exception as e:
            print(f"Failed to parse nonce response: {e}")
            return

        # Create and submit transaction
        transaction = create_transaction_to_submit(nonce, a, b)
        self.client.post("/api/submit", json=transaction)


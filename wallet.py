#!/usr/bin/env python

import os
from bsddb.db import *
from pickle import dumps, loads

import binascii
from bitcoin.key import CKey
from bitcoin.core import COutPoint, CTxIn, CTxOut, CTransaction


# Joric/bitcoin-dev, june 2012, public domain
import hashlib
import ctypes
import ctypes.util
import sys
import utils


ssl = ctypes.cdll.LoadLibrary (ctypes.util.find_library ('ssl') or 'libeay32')

def check_result (val, func, args):
    if val == 0: raise ValueError 
    else: return ctypes.c_void_p (val)

ssl.EC_KEY_new_by_curve_name.restype = ctypes.c_void_p
ssl.EC_KEY_new_by_curve_name.errcheck = check_result


b58_digits = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'

def base58_encode(n):
    l = []
    while n > 0:
        n, r = divmod(n, 58)
        l.insert(0,(b58_digits[r]))
    return ''.join(l)

def base58_decode(s):
    n = 0
    for ch in s:
        n *= 58
        digit = b58_digits.index(ch)
        n += digit
    return n

def base58_encode_padded(s):
    res = base58_encode(int('0x' + s.encode('hex'), 16))
    pad = 0
    for c in s:
        if c == chr(0):
            pad += 1
        else:
            break
    return b58_digits[0] * pad + res

def base58_decode_padded(s):
    pad = 0
    for c in s:
        if c == b58_digits[0]:
            pad += 1
        else:
            break
    h = '%x' % base58_decode(s)
    if len(h) % 2:
        h = '0' + h
    res = h.decode('hex')
    return chr(0) * pad + res

def base58_check_encode(s, version=0):
    vs = chr(version) + s
    check = dhash(vs)[:4]
    return base58_encode_padded(vs + check)

def base58_check_decode(s, version=0):
    k = base58_decode_padded(s)
    v0, data, check0 = k[0], k[1:-4], k[-4:]
    check1 = dhash(v0 + data)[:4]
    if check0 != check1:
        raise BaseException('checksum error')
    if version != ord(v0):
        raise BaseException('version mismatch')
    return data

def dhash(s):
    return hashlib.sha256(hashlib.sha256(s).digest()).digest()

def rhash(s):
    h1 = hashlib.new('ripemd160')
    h1.update(hashlib.sha256(s).digest())
    return h1.digest()
    
def get_addr(k, version=0):
    pubkey = k.get_pubkey()
    secret = k.get_secret()
    hash160 = rhash(pubkey)
    addr = base58_check_encode(hash160,version)
    payload = secret
    k.compressed = True
    if k.compressed:
        payload = secret + chr(1)
    pkey = base58_check_encode(payload, 128+version)
    return addr, pkey, binascii.hexlify(pubkey)
    
def gen_eckey(passphrase=None, secret=None, pkey=None, compressed=False, rounds=1, version=0):
    k = CKey()
    if passphrase:
        secret = passphrase.encode('utf8')
        for i in xrange(rounds):
            secret = hashlib.sha256(secret).digest()
    if pkey:
        secret = base58_check_decode(pkey, 128+version)
        compressed = len(secret) == 33
        secret = secret[0:32]
    k.generate(secret)
    k.set_compressed(compressed)
    return k
    
# helper functions
def getnewsubaccount():
    key = gen_eckey()
    address, private_key, public_key = get_addr(key)
    print "Address: ", address
    print "Private key: ", private_key
    print "Public key: ", public_key
    return {"address": address, "public_key": public_key, "private_key": private_key, "balance": 0.0, 'height' : 0, 'received' : []}

# Wallet class
class Wallet(object):
    def __init__(self, walletfile = "~/.bitcoinpy/wallet.dat"):
        self.walletfile = os.path.expanduser(walletfile)
        self.walletdir = os.path.split(self.walletfile)[0]
        self.db_env = DBEnv(0)
        self.db_env.open(self.walletdir, (DB_CREATE|DB_INIT_LOCK|DB_INIT_LOG|DB_INIT_MPOOL|DB_INIT_TXN|DB_THREAD|DB_RECOVER))
        
    # open wallet database
    def open(self, writable=False):
	    db = DB(self.db_env)
	    if writable:
		    DB_TYPEOPEN = DB_CREATE
	    else:
		    DB_TYPEOPEN = DB_RDONLY
	    flags = DB_THREAD | DB_TYPEOPEN
	    try:
		    r = db.open(self.walletfile, "main", DB_BTREE, flags)
	    except DBError:
		    r = True
	    if r is not None:
		    logging.error("Couldn't open wallet.dat/main. Try quitting Bitcoin and running this again.")
		    sys.exit(1)
	    return db
    	
    # if wallet does not exist, create it
    def initialize(self):
        if not os.path.isfile(self.walletfile):
            walletdb = self.open(writable = True)
            print "Initilizing wallet"
            subaccount = getnewsubaccount()
            walletdb['account'] = dumps({subaccount['address']: subaccount})
            walletdb['accounts'] = dumps(['account'])
            walletdb.sync()
            walletdb.close()

    # return an account
    def getaccount(self, accountname = None):
        if not accountname:
            accountname = "account"
        walletdb = self.open()
        # if wallet is not initialized, return
        if 'accounts' not in walletdb:
            print "Wallet not initialized ... quitting!"
            return None
        # if wallet is initialized
        accountnames = loads(walletdb['accounts'])
        if accountname not in accountnames:
            print "Error: Account not found"
            return
        # if account is in wallet
        account = loads(walletdb['account']) # FIXME: account = loads(walletdb[accountname])
        walletdb.close()
        return account

    # getaccounts
    def getaccounts(self):
        accounts = []
        walletdb = self.open()
        # if wallet is not initialized, return
        if 'accounts' not in walletdb:
            print "Wallet not initialized ... quitting!"
            return None
        # wallet is initialized
        accountnames = loads(walletdb['accounts'])
        walletdb.close()
        for accountname in accountnames:
            account = loads(walletdb[accountname])
            accounts.append(account)
        return accounts
                            
    # create and return a new address
    def getnewaddress(self, accountname = None):
        if not accountname:
            accountname = "account"
        walletdb = self.open(writable = True)
        # if wallet is not initialized
        if 'accounts' not in walletdb:
            print "Wallet not initialized ... quitting!"
            return None
        # if wallet is initialized
        subaccount = getnewsubaccount()
        accountnames = loads(walletdb['accounts'])
        if accountname in accountnames:
            account = loads(walletdb[accountname])
            account[subaccount['address']] = subaccount
        else:
            print "account: ", accountname, " not in accounts"
            print "creating new account" 
            account = {subaccount['address']: subaccount}
            # add the new account name to account names
            walletdb['accounts'] = dumps(accountnames.append(accountname))
        walletdb[accountname] = dumps(account)
        walletdb.sync()
        walletdb.close()
        return subaccount['public_key'], subaccount['address']
    
    # return balance of an account
    def getbalance(self, accountname):
        if not accountname:
            accountname = "account"
        walletdb = self.open()
        # if wallet is not initialized, return
        if 'accounts' not in walletdb:
            print "Wallet not initialized ... quitting!"
            return None
        # if wallet is initialized
        accountnames = loads(walletdb['accounts'])
        if accountname not in accountnames:
            print "Error: Account not found"
            return
        # if account is in wallet
        account = loads(walletdb['account']) # FIXME: account = loads(walletdb[accountname])
        walletdb.close()
        print account
        for address, subaccount in account.iteritems():
            subaccount['balance'] = self.chaindb.getbalance(subaccount['address'])
        return account

    # send to an address
    def sendtoaddress(self, toaddress, amount):        
        # select the input addresses
        funds = 0
        subaccounts = []
        accounts = self.getaccounts()
        for account in accounts:
            for subaccount in account:
                if subaccount['balance'] == 0:
                    continue
                else:
                    subaccounts.append(subaccount)
                    funds = funds + subaccount['balance']
                    if funds >= amount + utils.calculate_fees(None):
                        break
        
        # incase of insufficient funds, return
        if funds < amount + utils.calculate_fees(None):
            print "In sufficient funds, exiting, return"
            return
            
        # create transaction
        tx = CTransaction()
        
        # to the receiver
        txout = CTxOut()
        txout.nValue = amount
        txout.scriptPubKey = utils.address_to_pay_to_pubkey_hash(toaddress)
        tx.vout.append(txout)
        
        # from the sender
        nValueIn = 0
        public_keys = []
        private_keys = []
        for subaccount in subaccounts:
            # get received by from address
            previous_txouts = subaccount['received']
            for received in previous_txouts.iteritems():
                txin = CTxIn()
                txin.prevout = COutPoint()
                txin.prevout.hash = received['txhash']
                txin.prevout.n = received['n']
                txin.scriptSig = received[txin.prevout.n].scriptPubKey
                tx.vin.append(txin)
                nValueIn = nValueIn + received['value']
                public_keys.append(subaccount['public_key'])
                private_keys.append(subaccount['private_key'])
                if nValueIn >= amount + utils.calculate_fees(tx):
                    break
            if nValueIn >= amount + utils.calculate_fees(tx):
                break

        # calculate the total excess amount
        excessAmount = nValueIn - nValueOut
        # calculate the fees
        fees = utils.calculate_fees(tx)
        # create change transaction, if there is any change left
        if excessAmount > fees:
            change_txout = CTxOut()
            change_txout.nValue = excessAmount - fees
            changeaddress = subaccounts[0]['address']
            change_txout.scriptPubKey = utils.address_to_pay_to_pubkey_hash(changeaddress)
            tx.vout.append(change_txout)
        
        # calculate txhash
        tx.calc_sha256()
        txhash = tx.sha256
        # sign the transaction
        for public_key, private_key, txin in zip(public_key, private_keys, tx.vin):
            key = CKey()
            key.generate(('%064x' % private_key).decode('hex'))
            pubkey_data = key.get_pubkey()
            signature = key.sign(txhash)
            scriptSig = chr(len(signature)) + hash_type + signature + chr(len(public_key)) + public_key
            print "Adding signature: ", binascii.hexlify(scriptSig)
            txin.scriptSig = scriptSig
        return tx

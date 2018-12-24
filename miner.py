# NOTE: This is Python 3 code!


#############################################################################################################
# THIS IS A VERY INEFFICIENT MINER, AND SHOULD BE ONLY USED AS A REFERENCE TO CREATE MORE EFFICIENT SOLUTIONS
#############################################################################################################
#
# Please make sure to read the mining documentary at https://docs.bitcoinpy.io,
# to fully understand what is going on here
#
#############################################################################################################


from bitcoinrpc.authproxy import AuthServiceProxy, JSONRPCException
import datetime
import argparse
import time
import sys
import struct
import binascii
import random
from sha256 import SHA256
import os
import uuid

def readable_hashrate(b):
    if b < 1000:
        return '%i' % b + ' H/s'
    elif 1000 <= b < 1000000:
        return '%.1f' % float(b/1000) + ' kH/s'
    elif 1000000 <= b < 1000000000:
        return '%.1f' % float(b/1000000) + ' MH/s'
    elif 1000000000 <= b < 1000000000000:
        return '%.1f' % float(b/1000000000) + ' GH/s'
    elif 1000000000000 <= b:
        return '%.1f' % float(b/1000000000000) + ' TH/s'

def get_template(rpc, address):
    template = rpc.minegastemplate(address)
    print("[" + str(datetime.datetime.now().time()) + "]","updated template, target hash is",template['target'])
    return template

parser = argparse.ArgumentParser(description='BitcoinPy GAS Miner')
parser.add_argument('--rpc_user','-u', type=str, nargs=1,
                    help='your RPC user name')
parser.add_argument('--rpc_password', '-p', type=str, nargs=1,
                    help='your RPC password')
parser.add_argument('--rpc_endpoint', '-e', type=str, nargs=1,
                    help='your RPC host:port')
parser.add_argument('--address', '-a', type=str, nargs=1,
                    help='the address to receive the GAS mining rewards')
args = parser.parse_args()

# Let us create a connection first
rpc_connection = AuthServiceProxy("http://%s:%s@%s"%(args.rpc_user[0], args.rpc_password[0], args.rpc_endpoint[0]))

# How much time needs to pass before refetching the template / target and looking for new unspent outputs
MAX_INNER_LOOP_TIME = 5*60 # 5 minutes
HEART_BEAT_TIME = 10 # print hashrate every 10 seconds

while 1==1:

    # First we must get the "GAS mining template".
    # It contains the BitcoinPy payload (basically the mine transaction in its raw form, pre-prepared with your address as the receipient) as well as the current difficulty
    # All you will need to do from now on is to shuffle the late 16 bytes of the template (which are the nonce) until you find a transaction hash that meets the above target requirement
    template = get_template(rpc_connection, args.address[0])
    binarypayload = binascii.unhexlify(template['transaction'])
    numericaltarget = int(template['target'], 16)

    # since the GAS mining hash depends on all "input prevout's" of the transaction, we have to decide which inputs we want to pull in early on
    # Note: It does not depend on the inputs, but the input's prevouts! Making the signature of those inputs entirely irrelevant!

    unspents = rpc_connection.listunspent(1) # all with min. 1 confirmation
    used_vout = None
    for x in unspents:
        if x["amount"] > 0.01:
            used_vout = x
            break
    if used_vout == None:
        print("[" + str(datetime.datetime.now().time()) + "]","no unspent outputs greater than 0.01 BTC found ... retrying in 5 seconds")
        time.sleep( 5 )
        continue
    print("[" + str(datetime.datetime.now().time()) + "]","found a suitable vout",x["txid"] + ":" + str(x["vout"]))

    voutpreface = binascii.unhexlify(used_vout["txid"])[::-1] + used_vout["vout"].to_bytes(4, byteorder = 'big') 
    midstateinput = binarypayload[0:28]
    secondpart = binarypayload[28:]


    # Now, we have the mining template and one output that can most likely cover the BTC relay fees. We can now start an inner loop that will
    # either run for MAX_INNER_LOOP_TIME or until a valid hash was found and submitted
    start = time.time()
    last_heartbeat = start
    hashes = 0
    print("[" + str(datetime.datetime.now().time()) + "]","hashing loop started ...")

    startnoncerange = uuid.uuid4().int
    while 1==1:
        current = time.time()
        time_since_restart = current - start
        time_since_heartbeat = current - last_heartbeat

        # helper logic for restart and hashrate information
        if time_since_restart>=MAX_INNER_LOOP_TIME:
            break

        if time_since_heartbeat>=HEART_BEAT_TIME:
            last_heartbeat = current
            hrate = float(hashes) / float(time_since_heartbeat)
            print("[" + str(datetime.datetime.now().time()) + "]","hashrate over the last",round(time_since_heartbeat,2),"seconds:",readable_hashrate(hrate))
            hashes = 0

        # create hasher with midstate
        hashround1 = SHA256()
        hashround1.update(voutpreface)
        hashround1.update(midstateinput)
        hashround1.update(secondpart[:-16])
        
        # vary the second part in the last 16 bytes! We just generate any random 16 byte string
        startnoncerange+=1
        binvar = struct.pack('IIII', startnoncerange & ((1<<32) - 1), (startnoncerange>>32) & ((1<<32) - 1), (startnoncerange>>64) & ((1<<32) - 1), (startnoncerange>>96) & ((1<<32) - 1))
        hashround1.update(binvar)

        # hash second round
        hashround2 = SHA256()
        hashround2.update(hashround1.digest())

        # Final hash, swap endianness
        finalhash = hashround2.digest()[::-1]

        # get hex hash
        hdig = binascii.hexlify(finalhash)

        hashresult = int(hdig, 16)

        # This routine is just for submitting the result
        if hashresult < numericaltarget:

            print("[" + str(datetime.datetime.now().time()) + "]","found a valid hash:",hdig.decode('ascii'))
            time.sleep(1)
            submit_data = midstateinput + secondpart[:-16] + binvar

            try:
                p = rpc_connection.sendrawcontractpacket([{"txid": used_vout["txid"], "vout" : used_vout["vout"]}], binascii.hexlify(submit_data).decode('ascii'), 0.001)
                p = rpc_connection.signrawtransactionwithwallet(p)
                if "hex" in p:
                    p = rpc_connection.sendrawtransaction(p["hex"])
                else:
                    raise Exception("Could not sign with wallet")
                print("[" + str(datetime.datetime.now().time()) + "]","submitted gas mining TX:",p)
                print (" >>", binascii.hexlify(submit_data).decode('ascii'))
            except Exception as e:
                print("[" + str(datetime.datetime.now().time()) + "]","submission failed with error:",e)
            time.sleep(3)
            break
        hashes += 1




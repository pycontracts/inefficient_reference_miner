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

# Here, we configure how much time needs to pass before refetching the template / target and looking for new unspent outputs
MAX_INNER_LOOP_TIME = 5*60 # 5 minutes
HEART_BEAT_TIME = 10 # print hashrate every 10 seconds

while 1==1:

    # First we must get the "GAS mining template".
    # It contains the BitcoinPy payload (basically the mine transaction in its raw form, pre-prepared with your address as the receipient) as well as the current difficulty
    template = get_template(rpc_connection, args.address[0])
    binarypayload = binascii.unhexlify(template['transaction'])
    numericaltarget = int(template['target'], 16)

#############################################################################################################
# IMPORTANT INFORMATION
#############################################################################################################
#
# The RPC command looks like this:
# minegastemplate 2N9XtqgAeDHmM4Zq32YhzaUtP7a8nSDUDZA

# The GAS mining template answer looks like this:
# {"transaction": "030000000000000000000000000000000023324e3958747167416544486d4d345a71333259687a615574503761386e534455445a411055555555555555555555555555555555",
#  "target": "0000ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"}
#
# Transaction is a hex encoded serialized version of this C structure:
#    SerializablePayload pl;
#    std::vector<char> data;
#    for (int i = 0; i < 16; ++i)
#        data.push_back(0x55);
#    pl.data = std::string(data.begin(), data.end());
#    pl.gaslimit = 0;
#    pl.value = 0;
#    pl.command = CMD_MINER; // 0x03
#    pl.receiver = "2N9XtqgAeDHmM4Zq32YhzaUtP7a8nSDUDZA";
#
# ... with
#
# class SerializablePayload
# {
# public:
#    ...
#    uint8_t command;
#    uint64_t value;
#    uint64_t gaslimit;
#    std::string receiver;
#    std::string data;
#    ... }
#
# The last 16 bytes, here prefilled with all 0x55, can be varied by the miner
#############################################################################################################


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

#############################################################################################################
# IMPORTANT INFORMATION
#############################################################################################################
#
# The hash algorithm is a simple double SHA256d.
# Here is what needs to be hashed to obtain the correct HASH
#
# For each input (or rather its consumed COutPoint) (in this miner, we only have one) we have to write this into the hasher
# - TXID, in binary (not hex) form, and reversed [see example below].
# - VOUT, as big endian 32 bit integer
#
# Then, at the end, we hash in the entire "transaction" from above with the last 16 byte changed to whatever you want
# You can optimize a lot, when you take the first 64 byte (which are all static) and calculate a reusable midstate
# All what is left is less than one full SHA256 block, which can be hashed quite efficiently.
#
#
#############################################################################################################
#
# Here, a specific example of what bytes are hashed for one specific example
#
# 0799df867cb89d9b60be55419dcab1902383996b5ff0747f9c73517d1f4ccf31 <--- TXID (reversed), transaction was 0x31cf4c1f....
# 00000000 <--- big endian VOUT = 0
# 03 <--- Part of "transaction" from the "template" / means command type 0x03 = MINING
# 0000000000000000 <---- Part of "transaction" from the "template" / value transmitted, 64bit, must be 0 for mining
# 0000000000000000 <---- Part of "transaction" from the "template" / gaslimit to pay, 64bit, must be 0 for mining
# 23 <---- Part of "transaction" from the "template" / length of string receipient address
# 324e3958747167416544486d4d345a71333259687a615574503761386e534455445a41 <---- Part of "transaction" from the "template" / receipient address raw bytes
# 10 <--- Part of "transaction" from the "template" / Length of "rest", i.e., the nonce payload. Here 0x10 = 16
# 5795ef9cdec2ef93c34998d824d73b5f <---- OUR RANDOM 16 BYTES
#
# Technically, you can construct those bytes yourself and you do not need to call minegastemplate() via RPC at all.
# Also, be advised that the hash will come out of SHA256 reversed. So see it like below, you need to reverse it.
#
# AND THIS IS THE HASH THAT SHOULD COME OUT FOR THE EXAMPLE ABOVE
#
# 2018-12-24T12:14:49Z We saw a GAS-MINER transaction, credited 100000000000 + 0 (fees) satoshis in BTCGAS and sent to 2N9XtqgAeDHmM4Zq32YhzaUtP7a8nSDUDZA
# 2018-12-24T12:14:49Z | preupdate wallet transaction; old debit: 0, new debit: 0, old credit: 0, new credit: 100000000000
# 2018-12-24T12:14:49Z Hash was: 0000ceaa447004633363266352782fa80326e67e127f7458a5dfa4d7654d7356 [target 0000ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff]
#############################################################################################################



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




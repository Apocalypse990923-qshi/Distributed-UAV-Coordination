#!/usr/bin/python

# Set target (waypoint) positions for UAVs

import sys
import struct
import socket
import math
import time
import argparse
import glob
import subprocess
import threading
import datetime

from core.api.grpc import client
from core.api.grpc import core_pb2
import xmlrpc.client

uavs = []
seentargets = []
mynodeseq = 0
nodecnt = 0
protocol = 'none'
mcastaddr = '235.1.1.1'
port = 9100
ttl = 64
core = None
session_id = None 
notfoundsametrgnode = 0
filepath = '/tmp'
nodepath = ''

thrdlock = threading.Lock()
xmlproxy = xmlrpc.client.ServerProxy("http://localhost:8000", allow_none=True)


#---------------
# Define a CORE node
#---------------
class CORENode():
  def __init__(self, nodeid, track_nodeid, track_dist):
    self.nodeid = nodeid
    self.trackid = track_nodeid
    self.oldtrackid = track_nodeid
    self.trackdist = track_dist

  def __repr__(self):
    return str(self.nodeid) + " " + str(self.oldtrackid) + " " + str(self.trackdist)
    
    
#---------------
# Thread that receives UDP Advertisements
#---------------
class ReceiveUDPThread(threading.Thread):    
  def __init__(self):
    threading.Thread.__init__(self)
    
  def run(self):
    ReceiveUDP()
      

#---------------
# Calculate the distance between two modes (on a map)
#---------------
def Distance(node1, node2):
  return math.sqrt(math.pow(node2.position.y-node1.position.y, 2) + math.pow(node2.position.x-node1.position.x, 2))

#---------------
# Redeploy a UAV back to its original position
#---------------
def RedeployUAV(uavnode):
  print("Redeploy UAV")
  position = xmlproxy.getOriginalWypt()
  xmlproxy.setWypt(position[0], position[1])

#---------------
# Record target tracked to the proxy 
# Update UAV color depending if it is tracking a target
#---------------
def RecordTarget(uavnode):
  print("RecordTarget")
  xmlproxy.setTarget(uavnode.trackid)


#---------------
# Advertise the target being tracked over UDP
#---------------
def AdvertiseUDP(uavnodeid, trgtnodeid, trgnodedist):
  print("AdvertiseUDP")
  addrinfo = socket.getaddrinfo(mcastaddr, None)[0]
  sk = socket.socket(addrinfo[0], socket.SOCK_DGRAM)
  ttl_bin = struct.pack('@i', ttl)
  sk.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl_bin)
  buf = str(uavnodeid) + ' ' + str(trgtnodeid) + ' ' + str(trgnodedist)
  sk.sendto(buf.encode(encoding='utf-8',errors='strict'), (addrinfo[4][0], port))

#---------------
# Receive and parse UDP advertisments
#---------------
def ReceiveUDP():
  #print("Receive UDP")
  addrinfo = socket.getaddrinfo(mcastaddr, None)[0]
  sk = socket.socket(addrinfo[0], socket.SOCK_DGRAM)
  sk.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

  # Bind
  sk.bind(('', port))

  # Join group
  group_bin = socket.inet_pton(addrinfo[0], addrinfo[4][0])
  mreq = group_bin + struct.pack('=I', socket.INADDR_ANY)
  sk.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

  while 1:
    buf, sender = sk.recvfrom(1500)
    buf_str = buf.decode('utf-8')
    uavidstr, trgtidstr, trgdistfloat = buf_str.split(" ")
    uavnodeid, trgtnodeid, trgnodedist = int(uavidstr), int(trgtidstr), float(trgdistfloat)
    # Update tracking info for other UAVs
    uavnode = uavs[mynodeseq]

    if uavnode.nodeid != uavnodeid:
      UpdateTracking(uavnodeid, trgtnodeid, trgnodedist)
  
#---------------
# Update tracking info based on a received advertisement
#---------------
def UpdateTracking(uavnodeid, trgtnodeid, track_dist):

  if protocol == "udp":
    thrdlock.acquire()
    
  # Update corresponding UAV node structure with tracking info
  # if UAV node is in the UAV list
  in_uavs = False
  for uavnode in uavs:
    if uavnode.nodeid == uavnodeid:
      uavnode.trackid = trgtnodeid
      uavnode.trackdist = track_dist
      in_uavs = True

  # Otherwise add UAV node to UAV list
  if not in_uavs:
    node = CORENode(uavnodeid, trgtnodeid, track_dist)
    uavs.append(node)   
      
  if protocol == "udp":
    thrdlock.release()

#---------------
# Update waypoints for targets tracked, or track new targets
#---------------
def TrackTargets(covered_zone, track_range):
  #print("Track Targets")
  global notfoundsametrgnode
  uavnode = uavs[mynodeseq]
  uavnode.trackid = -1
  updatewypt = 0

  commsflag = 0
  if protocol == "udp":
    commsflag = 1

  potential_targets = xmlproxy.getPotentialTargets(covered_zone, track_range)

  print("UAV nodes: ", uavs)
  print("Potential Targets: ", potential_targets)

  if len(potential_targets) == 0:
    seentargets.clear()
    uavnode.oldtrackid = -1
    uavnode.trackid = -1
    RecordTarget(uavnode)
    notfoundsametrgnode = 0

  # If the other UAVs have same target, compare distance
  # If less, continue tracking and reset the other UAV to track new
  if uavnode.oldtrackid > 0:
    for uavnodetmp in uavs:
      if uavnodetmp.nodeid != uavnode.nodeid:
        if uavnodetmp.trackid == uavnode.oldtrackid:
          notfoundsametrgnode = 0
          seentargets.append(uavnode.oldtrackid)
          # if the other node shorter than current node dist
          if uavnodetmp.trackdist < uavnode.trackdist:
            print("Same target detected node %d target %d" % (uavnodetmp.nodeid, uavnodetmp.trackid))
            # current nod should track a new node
            uavnode.trackid = -1
            uavnode.oldtrackid = uavnode.trackid
            RecordTarget(uavnode)
            RedeployUAV(uavnode)
            # Advertise this UAV searching new node
            # if protocol == "udp":
            #   AdvertiseUDP(uavnode.nodeid, uavnode.trackid, uavnode.trackdist)
            break
          else:
            # the other uav need to reset
            uavnodetmp.trackid = -1
        else:
          notfoundsametrgnode += 1


  # if target being tracked by only this node, update
  if len(uavs) == 8 and notfoundsametrgnode > 25:
    uavnode.trackid = uavnode.oldtrackid
    RecordTarget(uavnode)

  #closedistfromtrg = sys.maxsize
  closedistfromtrg = track_range
  for trgtnode_id in potential_targets:
    # If this UAV was tracking this target before and it's still
    # in range then it should keep it.
    # Update waypoint to the new position of the target
    if uavnode.oldtrackid == trgtnode_id:
         # Keep the current tracking; no need to change
        # unless the track goes out of range
        print('Keep the current tracking; no need to change ', trgtnode_id)
        uavnode.trackid = trgtnode_id
        updatewypt = 1     

    # If this UAV was not tracking any target and finds one in range
    if uavnode.oldtrackid == -1 and (not trgtnode_id in seentargets):
      print("Node %d found potential target %d" % (uavnode.nodeid, trgtnode_id))
      trackflag = 0
      if commsflag == 1: # udp
        for uavnodetmp in uavs:
          # if target node is being tracked by other node
          if uavnodetmp.trackid == trgtnode_id or \
              (uavnodetmp.trackid == 0 and uavnodetmp.oldtrackid == trgtnode_id):
            print("Target ", trgtnode_id, " is being tracked already")
            trackflag = 1 # track flag = 1 -> target already being tracked
            break

      # target is not being tracked, this UAV should track the node
      if commsflag == 0 or trackflag == 0:
        # shoudl find the shortest target
        print("UAV node should track this target ", trgtnode_id)

        curnode = core.get_node(session_id, uavnode.nodeid).node
        trgnode = core.get_node(session_id, trgtnode_id).node
        dist = Distance(curnode, trgnode)

        # finding the shortest target
        if dist < closedistfromtrg:
          closedistfromtrg = dist
          uavnode.trackid = trgtnode_id
          uavnode.trackdist = dist
          updatewypt = 1 # update way point

  # END FOR LOOP

  if updatewypt == 1:
    # Update waypoint for UAV node
    print("Update waypoint")
    updatewypt = 0
    # get target node's info
    response = core.get_node(session_id, uavnode.trackid)
    node = response.node
    # get x, y coord
    trgtnode_x, trgtnode_y = node.position.x, node.position.y
    # update waypoint
    xmlproxy.setWypt(int(trgtnode_x), int(trgtnode_y))
    # RecordTarget(uavnode)

  # Advertise target being tracked if using comms
  if protocol == "udp":
    AdvertiseUDP(uavnode.nodeid, uavnode.trackid, uavnode.trackdist)

  # Reset current tracking info (0) for other UAVs if we're using comms
  # which means allow commons (udp)
  if commsflag == 1:
    for uavnodetmp in uavs:
      if uavnodetmp.nodeid != uavnode.nodeid:
        # Reset current tracking info
        uavnodetmp.oldtrackid = uavnodetmp.trackid
        uavnodetmp.trackid = 0
    
  # Record the target tracked for displaying proper colors
  # Re-deploy UAV if it's not track anything
  if uavnode.trackid != uavnode.oldtrackid:
    uavnode.oldtrackid = uavnode.trackid
    # record new target if changed
    # RecordTarget(uavnode)
    if uavnode.trackid == -1:
      RedeployUAV(uavnode)

#---------------
# main
#---------------
def main():
  global uavs
  global protocol
  global nodepath
  global mynodeseq
  global nodecnt
  global core
  global session_id
  global seentargets
  global notfoundsametrgnode

  # Get command line inputs 
  parser = argparse.ArgumentParser()
  parser.add_argument('-my','--my-id', dest = 'uav_id', metavar='my id',
                      type=int, default = '1', help='My Node ID')
  parser.add_argument('-c','--covered-zone', dest = 'covered_zone', metavar='covered zone',
                       type=int, default = '1200', help='UAV covered zone limit on X axis')
  parser.add_argument('-r','--track_range', dest = 'track_range', metavar='track range',
                       type=int, default = '600', help='UAV tracking range')
  parser.add_argument('-i','--update_interval', dest = 'interval', metavar='update interval',
                      type=int, default = '1', help='Update Inteval')
  parser.add_argument('-p','--protocol', dest = 'protocol', metavar='comms protocol',
                      type=str, default = 'none', help='Comms Protocol')

  
  # Parse command line options
  args = parser.parse_args()

  protocol = args.protocol

  # Create grpc client
  core = client.CoreGrpcClient("172.16.0.254:50051")
  core.connect()
  response = core.get_sessions()
  if not response.sessions:
    raise ValueError("no current core sessions")
  session_summary = response.sessions[0]
  session_id = int(session_summary.id)
  session = core.get_session(session_id).session

  # Populate the uavs list with current UAV node information
  mynodeseq = 0
  node = CORENode(args.uav_id, -1, 0)
  uavs.append(node)
  RedeployUAV(node)
  RecordTarget(node)
  nodecnt += 1
  
  if mynodeseq == -1:
    print("Error: my id needs to be in the list of UAV IDs")
    sys.exit()
    
  # Initialize values
  corepath = "/tmp/pycore.*/"
  nodepath = glob.glob(corepath)[0]
  msecinterval = float(args.interval)
  secinterval = msecinterval/1000

  if protocol == "udp":
    # Create UDP receiving thread
    recvthrd = ReceiveUDPThread()
    recvthrd.start()
        
  # Start tracking targets
  while 1:
    time.sleep(secinterval)

    if protocol == "udp":    
      thrdlock.acquire()
    
    TrackTargets(args.covered_zone, args.track_range)

    if protocol == "udp":
      thrdlock.release()


if __name__ == '__main__':
  main()

# This module tracks the latency from when targets nodes are placed in range of the uav nodes to when the last uav node tracks its target node. 
# The goal is to have all uav nodes track unique targets. But, the program should still complete if this does not happen. # The program creates an output log stored in "/tmp/norm_latency_avg.log"


#!/user/bin/python

import time
import datetime
import sys
import subprocess
import argparse
import os
import random

from core.api.grpc import client
from core.api.grpc import core_pb2

color_of_targets = dict()
uavs = dict()
filepath = '/tmp/'
iconpath = "/data/uas-core/icons/uav/"
curpath = os.path.dirname(os.path.abspath(__file__)) 
start_time = (0,0)
class TestCase():

    def __init__(self, core, session_id, id, name, protocol="none"):
        self.core = core
        self.session_id = session_id
        self.id = id
        self.name = name
        self.protocol = protocol
        self.starttime = None
        self.stoptime = None
        self.uav_target_pairs = dict()
        self.targets_to_move = []
        self.num_of_uavs = 0

    def setUavTargetPair(self, uav_id, target_id):
        if uav_id not in self.uav_target_pairs:
            if target_id != -1: 
                self.uav_target_pairs[uav_id] = [target_id]
        else: 
            targets = self.uav_target_pairs[uav_id]
            self.uav_target_pairs[uav_id].append(target_id)
    
    def updateUavTargetPairs(self, num_of_uavs, num_of_targets):
        count = 0
        for uav_id,target_id in uavs.items(): 

            response = self.core.get_node(self.session_id, uav_id)
            node = response.node

            # Get color from iconpath
            icon_file_path = node.icon
            start_index = len(iconpath)
            stop_index = len("_plane.png")
            color = icon_file_path[start_index:]
            color = color[:-stop_index]

            if color in color_of_targets:
                new_target_id = color_of_targets[color]
                if target_id != new_target_id: 
                    uavs[uav_id] = new_target_id
                    self.setUavTargetPair(uav_id, new_target_id)
            else:
                uavs[uav_id] = -1
            
            if uavs[uav_id] != -1: 
                count += 1
        return count == num_of_uavs if num_of_uavs <= num_of_targets else count >= num_of_targets

    def startTimer(self): 
        ts = time.time()
        st = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S.%f')
        self.starttime = (ts,st)
        if self.id=="1a":
            start_time = self.starttime

    def stopTimer(self):
        ts = time.time()
        st = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S.%f')
        self.stoptime = (ts,st)  
    
    def moveTargetsInRange(self, targets, timer=0, xuav=200, yuav=100):
        # Move targets within range of uavs	
        i = 1
        for target_id in targets:
            response = self.core.get_node(self.session_id, target_id)
            if (i % 2) == 0:
                pos = core_pb2.Position(x = xuav+200, y = yuav+(i/2-1)*150)
            else:
                pos = core_pb2.Position(x = xuav, y = yuav+((i-1)/2)*150)
            response = self.core.edit_node(self.session_id, target_id, position=pos)
            i += 1
            time.sleep(timer)
    
    def moveTargetsOutRange(self, xuav=1300, yuav=100):
        # Move targets out of range of uavs
        i = 1
        for color, target_id in color_of_targets.items():
            response = self.core.get_node(self.session_id, target_id)
            if (i % 2) == 0:
                pos = core_pb2.Position(x = xuav+100, y = yuav+(i/2-1)*150)
            else:
                pos = core_pb2.Position(x = xuav, y = yuav+((i-1)/2)*150)
            response = self.core.edit_node(self.session_id, target_id, position=pos)
            i += 1

    def runTest(self, 
                expired_time: int, 
                targets_to_move: list, 
                duration: float = 0.01, 
                time_between_targets: int = 0, 
                uavs_to_crash: list = [], 
                time_after_stop: int = 0):
        """
        :param expired_time: maximum time for uavs to choose a target
        :param targets_to_move: list of targets to move within range
        :param duration: sleep time (seconds) for continuous loop
        :param time_between_targets: time interval between moving targets
        :param uavs_to_crash: list of uavs to crash during test
        :param time_after_stop: sleep time (seconds) after stopping timer
        """
        num_of_uavs = len(uavs)-len(uavs_to_crash)
        self.num_of_uavs = num_of_uavs
        self.targets_to_move = targets_to_move
        self.startTimer()
        if len(uavs_to_crash) > 0: 
            self.crashUavs(uavs_to_crash)
        self.moveTargetsInRange(targets_to_move, time_between_targets)

        while expired_time > 0: 
            time.sleep(duration)
            result = self.updateUavTargetPairs(num_of_uavs, len(targets_to_move))
            if result: 
                break
            expired_time-= 1

        if expired_time < 1: 
            print("Time expired")

        self.stopTimer()
        time.sleep(time_after_stop)
        self.moveTargetsOutRange()
        self.formatTest()        
        if len(uavs_to_crash) > 0: 
            self.resetUavs()

    def crashUavs(self, list_of_uavs):
        print("Uavs to Crash:\t\t%s" % list_of_uavs)
        for uav_id in list_of_uavs: 
            cmd = "vcmd -c /tmp/pycore.{session_id}/n{node_id} -- pkill -f track_target_grpc.py".format(session_id=self.session_id, node_id=uav_id)
            #print(cmd)
            subprocess.run(cmd, stderr=subprocess.STDOUT, shell=True)

    def resetUavs(self):
        curpath = os.getcwd()
        #trackpath = curpath[:-4]
        cmd = "./../start_tracking_grpc.sh " + self.protocol
        subprocess.run([cmd], cwd=curpath, stderr=subprocess.STDOUT, shell=True)


    def checkUnique(self):
        list_of_targets = []
        unique = True
        for uav,targets in self.uav_target_pairs.items(): 
            list_of_targets += targets
        list_of_targets.sort()
        self.targets_to_move.sort()
        #print("List of Targets: ", list_of_targets, "\t # of Targets to Move: ", self.targets_to_move)

        if len(list_of_targets) == len(self.targets_to_move):
            return list_of_targets == self.targets_to_move
        elif len(list_of_targets) == self.num_of_uavs: 
            check_list = []
            for target in list_of_targets: 
                if target not in check_list: 
                    check_list.append(target)
                else: 
                    return False
            return True
        else:
            return False

    
    def formatTest(self):
        check_unique = self.checkUnique()
        time_diff = self.stoptime[0] - self.starttime[0]
        print("Latency:\t\t%0.4f seconds" % time_diff)
        #print("    Start Time:\t%s" % self.starttime[1])
        start_diff = self.starttime[0]-start_time[0]
        print("    Start Time:\t\t%0.4f seconds" % start_diff)
        #print("    Stop Time:\t%s" % self.stoptime[1])
        stop_diff = self.stoptime[0]-start_time[0]
        print("    Stop Time:\t\t%0.4f seconds" % stop_diff)
        print("Uav-Target Pairs:\t%s" %  self.uav_target_pairs)
        if check_unique: 
            print("Result:\t\t\tTest Case PASSED. All uavs are tracking different targets.")
        else: 
            print("Result:\t\t\tTest Case FAILED. Some uavs are tracking the same targets.")

    def documentTest(self, fptr, test_id, test_name):
        fptr.write("\n---------Test %s - %s ---------\n" % (test_id, test_name))
        check_unique = self.checkUnique()
        time_diff = self.stoptime[0] - self.starttime[0]
        fptr.write("Latency:\t\t%0.4f seconds\n" % time_diff)
        #fptr.write("    Start Time:\t%s\n" % self.starttime[1])
        #fptr.write("    Stop Time:\t%s\n" % self.stoptime[1])
        start_diff = self.starttime[0]-start_time[0]
        fptr.write("    Start Time:\t\t%0.4f seconds\n" % start_diff)
        stop_diff = self.stoptime[0]-start_time[0]
        fptr.write("    Stop Time:\t\t%0.4f seconds\n" % stop_diff)
        fptr.write("Uav-Target Pairs:\t%s\n" %  self.uav_target_pairs)
        if check_unique: 
            fptr.write("Result:\t\t\tTest Case PASSED. All uavs are tracking different targets.\n\n")
        else: 
            fptr.write("Result:\t\t\tTest Case FAILED. Some uavs are tracking the same targets.\n\n")
        return (1 if check_unique else 0)

def RecordTests(test_cases, file_name="latency.log"):

    numUnique = 0

    fpath = curpath + '/' + file_name
    #print("filepath" , fpath)
    fptr=open(fpath, 'w+')

    for i,test in enumerate(test_cases):
        numUnique += test.documentTest(fptr, test.id, test.name)

    numDuplicate = len(test_cases) - numUnique

    fptr.write("\n\nNumber of times uav-target pairings had all unique targets:\t%s\n" % numUnique)
    fptr.write("Number of times uav-target pairings had duplicate targets:\t%s\n\n\n" % numDuplicate)


def main():

    global uavs
    global color_of_targets
    global start_time

    # Get command line inputs 
    if len(sys.argv) >= 1:
        protocol  = str(sys.argv[1])
    else:
        print("move_node.py protocol\n")
        sys.exit()

    # Initialize Variables
    msecduration  = float(100)
    duration = msecduration/1000
    colors = ['blue', 'yellow', 'green', 'red', 'lime', 'orange', 'pink', 'purple', 'lavender', 'cyan']
    uavs = {1:-1, 2:-1, 3:-1, 4:-1, 6:-1, 7:-1, 8:-1, 9:-1}    
    color_of_targets = {colors[0]: 11, colors[1]: 12, colors[2]: 13, colors[3]: 14, 
            colors[4]: 16, colors[5]: 17, colors[6]: 18, colors[7]: 19}
    tests = []

    time_expired = 2500

    # Core grpc session
    core = client.CoreGrpcClient()
    core.connect()
    response = core.get_sessions()
    if not response.sessions:
        raise ValueError("no current core sessions")
    session_summary = response.sessions[0]
    session_id = int(session_summary.id)
    session = core.get_session(session_id).session

    ts = time.time()
    st = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S.%f')
    start_time = (ts,st)
# Test 1a - Move all targets within range - 2 second interval between
    print("\n--------- Test 1a - Move all targets within range - 2 second interval between ------------")
    # initialize variables 
    uavs = {1:-1, 2:-1, 3:-1, 4:-1, 6:-1, 7:-1, 8:-1, 9:-1}    
    # run test 
    test1 = TestCase(core, session_id, "1a", "Move all targets within range - 2 second interval between", protocol) 
    test1.runTest(time_expired, [11,12,13,14,16,17,18,19], duration, time_between_targets=2)
    tests.append(test1)
    time.sleep(5)

# Test 1b - Move all targets within range - 2 second interval between - Out of Order
    print("\n--------- Test 1b - Move all targets within range - 2 second interval between - Out of Order ------------")
    # initialize variables 
    uavs = {1:-1, 2:-1, 3:-1, 4:-1, 6:-1, 7:-1, 8:-1, 9:-1}  
    shuffle_targets = [11,12,13,14,16,17,18,19]
    random.shuffle(shuffle_targets)
    # run test   
    test1 = TestCase(core, session_id, "1b", "Move all targets within range - 2 second interval between - Out of Order", protocol) 
    test1.runTest(time_expired, shuffle_targets, duration, time_between_targets=2)
    tests.append(test1)
    time.sleep(5)

# Test 2a - Move 6 out of 8 targets within range - 2 second interval between
    print("\n--------- Test 2a - Move 6 out of 8 targets within range - 2 second interval between ------------")
    # initialize variables 
    uavs = {1:-1, 2:-1, 3:-1, 4:-1, 6:-1, 7:-1, 8:-1, 9:-1} 
    # run test      
    test2 = TestCase(core, session_id, "2a", "Move 6 out of 8 targets within range - 2 second interval between", protocol)
    test2.runTest(time_expired, [11,12,13,14,16,17], duration, time_between_targets=2)
    tests.append(test2)
    time.sleep(5)

# Test 2b - Move 6 out of 8 targets within range - 2 second interval between
    print("\n--------- Test 2b - Move 6 out of 8 targets within range - 2 second interval between - Out of Order ------------")
    # initialize variables
    uavs = {1:-1, 2:-1, 3:-1, 4:-1, 6:-1, 7:-1, 8:-1, 9:-1}    
    shuffle_targets = [11,12,13,14,16,17,18,19]
    random.shuffle(shuffle_targets)
    # run test
    test2 = TestCase(core, session_id, "2b", "Move 6 out of 8 targets within range - 2 second interval between - Out of Order", protocol)
    test2.runTest(time_expired, shuffle_targets[:6], duration, time_between_targets=2)
    tests.append(test2)
    time.sleep(5)

# Test 3a - Move all targets within range 
    print("\n--------- Test 3a - Move all targets within range  ------------")
    # initialize variables
    uavs = {1:-1, 2:-1, 3:-1, 4:-1, 6:-1, 7:-1, 8:-1, 9:-1}    
    # run test
    test3 = TestCase(core, session_id, "3a" , "Move all targets within range", protocol)
    test3.runTest(time_expired, [11,12,13,14,16,17,18,19], duration, time_after_stop=2)
    tests.append(test3)
    time.sleep(5)

# Test 3b - Move all targets within range - Out of Order
    print("\n--------- Test 3b - Move all targets within range - Out of Order ------------")
    # initialize variables
    uavs = {1:-1, 2:-1, 3:-1, 4:-1, 6:-1, 7:-1, 8:-1, 9:-1}  
    shuffle_targets = [11,12,13,14,16,17,18,19]
    random.shuffle(shuffle_targets)  
    # run test
    test3 = TestCase(core, session_id, "3b" , "Move all targets within range - Out of Order", protocol)
    test3.runTest(time_expired, shuffle_targets, duration, time_after_stop=2)
    tests.append(test3)
    time.sleep(5)

# Test 4 - Crash 1 UAV and move all targets within range 
    print("\n--------- Test 4 - Crash 1 UAV and move all targets within range  ------------")
    # initialize variables
    uavs = {1:-1, 2:-1, 3:-1, 4:-1, 6:-1, 7:-1, 8:-1, 9:-1}    
    list_of_uavs = list(uavs.keys())
    index = random.randint(0,len(list_of_uavs)-1)
    uavs_to_crash = []
    uavs_to_crash.append(list_of_uavs[index])
    shuffle_targets = [11,12,13,14,16,17,18,19]
    random.shuffle(shuffle_targets)  
    # run test
    test4 = TestCase(core, session_id, "4", "Crash 1 UAV and move all targets within range", protocol)
    test4.runTest(time_expired, shuffle_targets, duration, uavs_to_crash=uavs_to_crash, time_after_stop=5)
    tests.append(test4)
    time.sleep(5)

# Test 5 - Crash 2 UAV and move all targets within range
    print("\n--------- Test 5 - Crash 2 UAV and move all targets within range ------------")
    # initialize variables
    uavs = {1:-1, 2:-1, 3:-1, 4:-1, 6:-1, 7:-1, 8:-1, 9:-1}    
    uavs_to_crash = []
    list_of_uavs = list(uavs.keys())
    index = random.randint(0,(len(list_of_uavs)-1)//2)
    uavs_to_crash.append(list_of_uavs[index])
    index = random.randint(((len(list_of_uavs)-1)//2)+1, len(list_of_uavs)-1)
    uavs_to_crash.append(list_of_uavs[index])
    shuffle_targets = [11,12,13,14,16,17,18,19]
    random.shuffle(shuffle_targets) 
    # run test 
    test5 = TestCase(core, session_id, "5" , "Crash 2 UAV and move all targets within range", protocol)
    test5.runTest(time_expired, shuffle_targets, duration, uavs_to_crash=uavs_to_crash, time_after_stop=5)
    tests.append(test5)
    time.sleep(5)

# Test 6a - Move 6 out of 8 targets within range 
    print("\n--------- Test 6a - Move 6 out of 8 targets within range  ------------")
    # initialize variables
    uavs = {1:-1, 2:-1, 3:-1, 4:-1, 6:-1, 7:-1, 8:-1, 9:-1}    
    # run test
    test6 = TestCase(core, session_id, "6a" , "Move 6 out of 8 targets within range", protocol)
    test6.runTest(time_expired, [11,12,13,14,16,17], duration, time_after_stop=5)
    tests.append(test6)
    time.sleep(5)

# Test 6b - Move 6 out of 8 targets within range - Out of Order
    print("\n--------- Test 6b - Move 6 out of 8 targets within range - Out of Order ------------")
    # initialize variables
    uavs = {1:-1, 2:-1, 3:-1, 4:-1, 6:-1, 7:-1, 8:-1, 9:-1}  
    shuffle_targets = [11,12,13,14,16,17,18,19]
    random.shuffle(shuffle_targets)  
    # run test
    test6 = TestCase(core, session_id, "6b" , "Move 6 out of 8 targets within range - Out of Order", protocol)
    test6.runTest(time_expired, shuffle_targets[:6], duration, time_after_stop=5)
    tests.append(test6)
    time.sleep(5)

# Write test to file
    RecordTests(tests)


if __name__ == '__main__':
    main()


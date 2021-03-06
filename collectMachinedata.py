
''' Software to gather Plc data from Delphi factory shops as a part of Delphi IOT '''


__author__     =      "Vikram Shelke"
__credits__    =      ["Wipro Team", "Delphi Team"]
__version__    =      "1.2"
__maintainer__ =      "Vikram Shelke"
__email__      =      "vikram.shelke@wipro.com"
__date__       =      "23/08/2018"
__status__     =      "Production" 


import RPi.GPIO as GPIO
import socket
import pytz
import time
import datetime
import urllib3
import logging
import urllib2
import sys
import ConfigParser
import uuid
import buffer
import wiprobuffer
import Queue
#for python 2
import urllib
import threading
import re
from time import gmtime, strftime, sleep
from logging.handlers import RotatingFileHandler
from logging import handlers

#Check python version here and confirm if this code is reqiuired
#for python 3
#from urllib.parse import urlencode

http = urllib3.PoolManager()
q=Queue.Queue(maxsize=10) # que to hold messages temporary
wiproq=Queue.Queue(maxsize=10)


#------------------global arrays to hold each machine information -------------------------------------------------- 

machineCycleSignal=[]                       # list to hold ECP  Signal
machineGoodbadPartSignal=[]                 #  list to hold QSP Signals  
machineName =[]                             #  this holds machine names  
machineobject=[]                            #  list to hold machine instances
machine_cycle_timestamp=[]                  # timestamp for each machine get stored in this list
finalmessage=[]                             #  whole message with timestamp + machine name + quality 
send_message=[]                             #  every machine has seprate send message for sending final message
machine_good_badpart_pinvalue=[]            #  this hold good/bad part pin values
machine_cycle_risingEdge_detected=[]        #   this hold rising edges for ECP
machine_cycle_pinvalue=[]                   # this checks validity of machine cycle pulse  for each machine




#------------------------------------------------------------------------------------------------------------------



# ---------------------------------------Read Already updated machine configuration from fetchConfiguration.py  --------

config = ConfigParser.ConfigParser()
config.optionxform = str
config.readfp(open(r'machineConfig.txt'))
path_items = config.items( "machine-config" )
LOCATION=None
Logic=''
DeviceModel=''
DeviceType=''
DEVICENAME=''
PUD=''
for key, value in path_items:
        if 'DeviceName'in key:
                DEVICENAME = value
        if 'Facility'in key:
                LOCATION = value
        if 'Logic'in key:
                Logic = value
        if 'DeviceModel'in key:
                DeviceModel = value
        if 'DeviceType'in key:
                DeviceType = value
        if 'TotalMachines' in key:
                totalMachines=int(value)
        if 'PUD'  in key:
                PUD = value;
        if 'MACHINE' in key:
                machineName.append(value)
        if 'CYCLE' in key:
                machineCycleSignal.append(int (value))
        if '_Quality' in key:
                        if key == machineName[-1]+"_Quality":
                                if value !="NO":
                                        machineGoodbadPartSignal.append(int(value))
                                else:
                                        machineGoodbadPartSignal.append(0)

#Change Logic as per device

if Logic == 'Inverted': #For IONO PI and DIN Pi, check event is 1
        VerificationLogic = 0
else : #For Piegon PI and Raspberry Pi, check event is 0
        VerificationLogic = 1

#----------------------------------------------------------------------------------------------------------------------


# --------------------------------initalization---------------------

for k in range (totalMachines):
        machine_good_badpart_pinvalue.append(0)
        machine_cycle_risingEdge_detected.append(0)
        machine_cycle_pinvalue.append(0)
        machine_cycle_timestamp.append("NODATA")
        finalmessage.append("NODATA")
        send_message.append("NODATA")


#---------------------------------------------------  log mechanism  configuration ------------------------------------


log_config = ConfigParser.ConfigParser()
log_config.readfp(open(r'logConfig.txt'))
LOG= log_config.get('log-config', 'LOG_ENABLE')
HOST=log_config.get('log-config', 'DELPHI_HOST')
PORT=log_config.get('log-config', 'DELPHI_PORT')
WIPROHOST=log_config.get('log-config', 'WIPRO_HOST')
WIPROPORT=log_config.get('log-config', 'WIPRO_PORT')
LOGFILE=log_config.get('log-config','LOGFILE')
SENDURL=log_config.get('log-config','SENDURL')
log = logging.getLogger('')
log.setLevel(logging.DEBUG)
logging.getLogger("urllib3").setLevel(logging.ERROR)
if LOG == 'True':
        log.disabled = False
else :
        log.disabled=True


# write to coonsle screen
#formatter_stdout = logging.Formatter("%(asctime)s %(levelname)s - %(message)s")
formatter_stdout = logging.Formatter("%(levelname)s - %(message)s")
log_stdout = logging.StreamHandler(sys.stdout)
log_stdout.setFormatter(formatter_stdout)
log.addHandler(log_stdout)
#use %(lineno)d for printnig line  no

# write logs to file with rotating file handler which keeps file size limited 

formatter_file = logging.Formatter('%(asctime)s %(levelname)s %(message)s',"%Y-%m-%d %H:%M:%S")
#formatter_file = logging.Formatter("%(asctime)s %(levelname)s - %(message)s")
log_file = handlers.RotatingFileHandler(LOGFILE, maxBytes=(1000000), backupCount=3)
log_file.setFormatter(formatter_file)
log.addHandler(log_file)

#--------------------------------------------------------------------------------------------------------------------



#----------------------------------------------------   GPIO settings   -----------------------------------------------

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)


for setupPinAsInput in range(len(machineCycleSignal)):
        #log.debug( "setting  GPIO%d as input ",machineCycleSignal[setupPinAsInput])
        #comment out above line to check where gpio setting is done on required pin for ECP
        if PUD =='UP':                                   # check Device model as per table
                GPIO.setup(machineCycleSignal[setupPinAsInput], GPIO.IN, pull_up_down=GPIO.PUD_UP)
        elif PUD == 'DOWN':
                GPIO.setup(machineCycleSignal[setupPinAsInput], GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        else:
                GPIO.setup(machineCycleSignal[setupPinAsInput], GPIO.IN)

for setupPinAsInput in range(len(machineGoodbadPartSignal)):

        if machineGoodbadPartSignal[setupPinAsInput]!=0 :
                #log.debug( "setting GPIO%d as input ",machineGoodbadPartSignal[setupPinAsInput])
                # comment out above line to check gpio setting is done on required pin for QSP
                if PUD =='UP':
                        GPIO.setup(machineGoodbadPartSignal[setupPinAsInput], GPIO.IN, pull_up_down=GPIO.PUD_UP)
                elif PUD =='DOWN':
                        GPIO.setup(machineGoodbadPartSignal[setupPinAsInput], GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
                else:
                        GPIO.setup(machineGoodbadPartSignal[setupPinAsInput], GPIO.IN)


#-------------------------------------------------------------------------------------------------------------------

log.debug('DeviceName:%s',DEVICENAME)
log.debug('Location:%s',LOCATION)
log.debug('Logic:%s',Logic)
log.debug('DeviceModel:%s',DeviceModel)
log.debug('DeviceType:%s',DeviceType)
log.debug('PUD:%s',PUD)
log.debug('machines connected   :%s',machineName)
log.debug('Machine cycle signal :%s',machineCycleSignal)
log.debug('Machine OK/NOTOK signals :%s',machineGoodbadPartSignal)


#Base Machine class

class Machine:
        'Common base class for all machines'
        MachineCount = 0
        def __init__(self, machine_cycle_rising_edge, machine_cycle_falling_edge, machine_cycle_pulse_time):
                self.machine_cycle_rising_edge = machine_cycle_rising_edge
                self.machine_cycle_falling_edge = machine_cycle_falling_edge
                self.machine_cycle_pulse_time = machine_cycle_pulse_time

        def machine_cycle_starttime(self):
                self.machine_cycle_rising_edge=time.time()

        def machine_cycle_stoptime(self):
                self.machine_cycle_falling_edge=time.time()

        def machine_cycle_cleartime(self):
                self.machine_cycle_rising_edge=0
                self.machine_cycle_falling_edge=0

        def machine_cycle_pulseTime(self,machinename):
                self.machinename=machinename
                self.machine_cycle_pulse_time=self.machine_cycle_falling_edge-self.machine_cycle_rising_edge
                log.debug ("Total Duration of MACHINE CYCLE SIGNAL for %s :%s ",machinename,str(self.machine_cycle_pulse_time))
                if self.machine_cycle_pulse_time >=2 and self.machine_cycle_pulse_time <= 4 :
                        return 1
                else:
                        return 0


#-------------------------------------------------------------------------------------------------------------------------------
'''
 send data function is used to send data to NiFi
 @param: timestamp
 @param:machinename
 @param:data ,is quality information

'''
#-------------------------------------------------------------------------------------------------------------------------------

def sendDataToDelphi(timestamp,machinename,data):
        data_send_from_machine_status=0
        fields={'ts':timestamp,'loc':LOCATION,'mach':machinename,'data':data}
        encoded_args = urllib.urlencode(fields)
        url = 'http://' + HOST + ':' + PORT + '/' + SENDURL +'?' + encoded_args
        try:
                r = http.request('GET', url,timeout=2.0)
                data_send_from_machine_status=r.status
        except urllib3.exceptions.MaxRetryError as e:
                data_send_from_machine_status=0
        if data_send_from_machine_status != 200 :
                if data_send_from_machine_status==0:
                        log.error(" Not able to send data to Delphi Azure: Connection Error")
                else:
                        log.debug("HTTP send status to Delphi NiFi: %d",data_send_from_machine_status)
                buffer.push(timestamp+" "+LOCATION+ " " + machinename +" "+data)
        else:
                log.debug("HTTP send status to Delphi NiFi: %d",data_send_from_machine_status)



def sendDataToWipro(timestamp,machinename,data):
        data_send_from_machine_status=0
        fields={'ts':timestamp,'loc':LOCATION,'mach':machinename,'data':data}
        encoded_args = urllib.urlencode(fields)
        url1 = 'http://' + WIPROHOST + ':' + WIPROPORT + '/get?' + encoded_args
        logging.debug(url1)
        try:
                r = http.request('GET', url1,timeout=2.0)
                data_send_from_machine_status=r.status
        except urllib3.exceptions.MaxRetryError as e:
                data_send_from_machine_status=0
        if data_send_from_machine_status != 200 :
                if data_send_from_machine_status==0:
                        logging.error(" Not able to send data to wipro Azure : Connection Error")
                else:
                        logging.debug("HTTP send status to Wipro NiFi : %d",data_send_from_machine_status)
                wiprobuffer.push(timestamp+" "+LOCATION+ " " + machinename +" "+data)
        else:
                logging.debug("HTTP send status  Wipro NiFi: %d",data_send_from_machine_status)






#---------------------------------------------------------------------------------------------------------------------------------------
'''
function to check network connectivity to Delphi NiFi

'''
#-----------------------------------------------------------------------------------------------------------------------------------------

def NiFiconnectionStatus_Delphi():
        
        conn_url = 'http://' + HOST + ':' + PORT + '/' + SENDURL +'?'
        try:
                r = http.request('GET', conn_url,timeout=2.0)    
                return str(r.status)
        except:
                return False


def NiFiconnectionStatus_Wipro():
        url1 = 'http://' + WIPROHOST + ':' + WIPROPORT + '/get?'
        try:
                
                r = http.request('GET', url1,timeout=2.0) 
        #log.debug("returnig true")
                return str(r.status)
        except:
    #   log.debug("returnig false---------------")
                return False






##plc machine 1 data collection
def plcMachine1(channel):
        process_machine_data(0)

##data collection machine 2
def plcMachine2(channel):
        process_machine_data(1)

##data collection machine 3
def plcMachine3(channel):
        process_machine_data(2)

## data collection machine 4
def plcMachine4(channel):
        process_machine_data(3)

## data collection machine 5
def plcMachine5(channel):
        process_machine_data(4)
        
## data collection machine 6
def plcMachine6(channel):
        process_machine_data(5)

## data collection machine 7
def plcMachine7(channel):
        process_machine_data(6)
        
## data collection machine 8
def plcMachine8(channel):
        process_machine_data(7)

def plcMachine9(channel):
        process_machine_data(8)

def plcMachine10(channel):
        process_machine_data(9)



#------------------------------------------------------------------------------------------------------------------------------

''' 
        process_machine_data function gathers Rising and falling Edges, calculate pulse widh and quality of parts
        for respective machine 
        @param:  machineNo 
        @Return: none
'''
#------------------------------------------------------------------------------------------------------------------------------


def process_machine_data(machineNo):

        global q
        global wiproq
        time.sleep(0.1)
        if (GPIO.input(machineCycleSignal[machineNo])==VerificationLogic): # dry contact closed on machine cycle pin
                if machine_cycle_risingEdge_detected[machineNo] == 0:
                        machine_cycle_risingEdge_detected[machineNo] = 1
                        log.debug ("Rising edge : %s Cycle Signal ",machineName[machineNo])
                        machineobject[machineNo].machine_cycle_starttime()
                        if machineGoodbadPartSignal[machineNo]==0:
                                #print "no goodbad part"
                                pass
                        else:
                                if (GPIO.input(machineGoodbadPartSignal[machineNo])==VerificationLogic): # check value of good_badpart_signal and set it to 1 if ok
                                        machine_good_badpart_pinvalue[machineNo]=1
                                else: #good_badpart is not ok
                                        machine_good_badpart_pinvalue[machineNo]=0
                else:
                        log.debug ("Multiple Rising Edge detected on %s", machineName[machineNo])
        else: # dry contact opend falling edge detected for machine_cycle pin
                if machine_cycle_risingEdge_detected[machineNo] == 1:
                        log.debug ("Falling edge : %s Cycle Signal ",machineName[machineNo])
                        machineobject[machineNo].machine_cycle_stoptime()
                        machine_cycle_risingEdge_detected[machineNo]=0
                        machine_cycle_timestamp[machineNo]=datetime.datetime.now(tz=pytz.UTC).replace(microsecond=0).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]+"+00:00"
                        machine_cycle_pinvalue[machineNo]=machineobject[machineNo].machine_cycle_pulseTime(machineName[machineNo])
                        if machine_cycle_pinvalue[machineNo]==1:
                                if machineGoodbadPartSignal[machineNo]==0:
                                        #print "no goodbad part"
                                        pass
                                else:
                                        if(GPIO.input(machineGoodbadPartSignal[machineNo])==VerificationLogic): # valid pulse
                                                machine_good_badpart_pinvalue[machineNo]=1
                                        else:
                                                machine_good_badpart_pinvalue[machineNo]=0
                                #try:
                                #        lock.acquire()
                                finalmessage[machineNo]="Quality"+":"+str(machine_good_badpart_pinvalue[machineNo])
                                log.debug(finalmessage[machineNo])
                                send_message[machineNo]=machine_cycle_timestamp[machineNo]+" "+machineName[machineNo]+" "+finalmessage[machineNo]
                                q.put(send_message[machineNo])
                                q.task_done()
                                wiproq.put(send_message[machineNo])
                                
                                wiproq.task_done()
                        else:
                                log.debug(" %s cycle pulse width is invalid",machineName[machineNo])
                machineobject[machineNo].machine_cycle_cleartime()



# -------------------------------------------------------------------------------------------------------------------------------------------
'''
   get_mac function extract the mac address from system 

'''
#--------------------------------------------------------------------------------------------------------------------------------

def get_mac():
        mac = ':'.join(re.findall('..', '%012x' % uuid.getnode()))
        return mac

mac=str(get_mac())




#------------------------ create machine object and call function as per no of machine connected to device----------------------------------


plcMachine = lambda totalMachines: eval("plcMachine"+str(totalMachines))
for addDetectionOnPin in range (totalMachines):
        #log.debug( "added machine cycle detection on GPIO%d",machineCycleSignal[addDetectionOnPin])
        #comment out above line to check , interrupt is added for detection on pins which are reqiured for ECP  
        GPIO.add_event_detect(machineCycleSignal[addDetectionOnPin], GPIO.BOTH, callback=plcMachine(addDetectionOnPin+1),bouncetime=200)

for m in range (totalMachines):
        machineobject.append(Machine(0, 0, 0))




#--------------------------------------------------------------------------------------------------------------------------------------------

'''   
    machineData function,which is continious running thread gets executed on every occurence of valid machine Cycle Signal 
    @ param: q which denotes valid message is available in queue

'''
#------------------------------------------------------------------------------------------------------------------------------------------

def machineData(q):
        log.debug(" Machine thread for sending data to Delphi Azure started ")
        messagesSinceLastReboot=0
        fd = open("machineCount.txt", "w+")
        fd.write ('TimeStamp of first MachineCycle signal received :0000-00-00T00:00:00.000+00:00 \n')
        #fd.write(str(totalMessage))
        fd.close()
        while True:
                data=q.get()  #wait until data is avalable  in que
                messagesSinceLastReboot= messagesSinceLastReboot+1
                log.info("machine Cycle signal received since last Reboot :%d",messagesSinceLastReboot)
                dataToSend=data.split()
                if messagesSinceLastReboot==1:        
                        log.debug("writing timestamp")
                        with open("machineCount.txt", "r+") as file: 
                                file.write ('TimeStamp of first MachineCycle signal received :'+str(dataToSend[0]))  
                sendDataToDelphi(dataToSend[0],dataToSend[1],dataToSend[2])
        log.debug("machine data thread for Delphi Azure exited")


def machineDatatowipro(wiproq):
        logging.debug("machine thread for sending data to Wipro azure started ")
        
        while True:
                dataw=wiproq.get()
                dataToSendwipro=dataw.split()
                sendDataToWipro(dataToSendwipro[0],dataToSendwipro[1],dataToSendwipro[2])
        logging.debug("machine data thread for Wipro Azure exited")





#------------------------------------------------------------------------------------------------------------------------------------------
'''
    below part starts thread and wait infinite loop it checks NiFi connection status on every 1 minute 
    it tries to send data available in buffer if any.

'''
#--------------------------------------------------------------------------------------------------------------------------------------------


t = threading.Thread(name = "sendDataThread", target=machineData, args=(q,))
twipro = threading.Thread(name = "sendDataThread", target=machineDatatowipro, args=(wiproq,))
t.start()
twipro.start()

log.debug("Data collection started")
try:
        while True:
                if NiFiconnectionStatus_Delphi()=='200':
                        log.debug( " Connection status to Delphi NiFi for edge device[%s] : CONNECTED ",str(get_mac()))
                        data=buffer.pop().rstrip()
                        if data!="-1":
                                while data!="-1":
                                        dataTosend=data.split()
                                        if len(dataTosend)!=0:
                                                sendDataToDelphi(dataTosend[0],dataTosend[2],dataTosend[3])
                                                time.sleep(3)
                                                data=buffer.pop().rstrip()
                else:
                        log.error(" Connection status to Delphi NiFi : NO NETWORK ")

                if NiFiconnectionStatus_Wipro()=='200':
                        logging.debug( " Connection status to wipro NiFi for edge device[%s]: CONNECTED ",str(get_mac()))
                        #logging.debug("MAC address of Edge Device: %s", str(get_mac()))
                        data1=wiprobuffer.pop().rstrip()
                        if data1!="-1":
                                while data1!="-1":
                                        dataTosendwipro=data1.split()
                                        if len(dataTosendwipro)!=0:
                        #log.debug("sending data to wipro")
                                                sendDataToWipro(dataTosendwipro[0],dataTosendwipro[2],dataTosendwipro[3])
                                                time.sleep(3)
                        
                                                data1=wiprobuffer.pop().rstrip() # this is breaking inner while condition
                else:
                        logging.error(" Connection status to wipro NiFi : NO NETWORK ")


                time.sleep(60)


except KeyboardInterrupt:
        log.debug(" Quit ")
        GPIO.cleanup()

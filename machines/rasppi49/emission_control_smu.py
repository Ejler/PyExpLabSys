import time
import threading
import PyExpLabSys.drivers.cpx400dp as CPX
import PyExpLabSys.auxiliary.pid as pid
from PyExpLabSys.common.value_logger import ValueLogger
from PyExpLabSys.common.loggers import ContinuousLogger
from PyExpLabSys.common.sockets import LiveSocket
from PyExpLabSys.common.sockets import DataPushSocket
from PyExpLabSys.common.sockets import DateDataPullSocket
from PyExpLabSys.common.utilities import get_logger
import PyExpLabSys.drivers.keithley_smu as smu
import emission_tui
import credentials

LOGGER = get_logger('Emission', level='info', file_log=True,
                    file_name='emission_log.txt', terminal_log=False)

class EmissionControl(threading.Thread):
    """ Control the emission of a filament. """
    def __init__(self):
        threading.Thread.__init__(self)
        channels = ['setpoint', 'emission', 'ionenergy']
        self.datasocket = DateDataPullSocket('emission_tof', channels,
                                             timeouts=[999999, 1.0, 999999999])
        self.datasocket.start()
        self.pushsocket = DataPushSocket('tof-emission-push_control', action='enqueue')
        self.pushsocket.start()
        self.livesocket = LiveSocket('tof-emission', channels, 1)
        self.livesocket.start()
        self.measured_voltage = 0
        self.filament = {}
        port = '/dev/serial/by-id/usb-TTI_CPX400_Series_PSU_C2F952E5-if00'
        self.filament['device'] = CPX.CPX400DPDriver(1, device=port)
        self.filament['voltage'] = 0
        self.filament['current'] = 0
        self.filament['idle_voltage'] = 1.7
        self.filament['device'].set_current_limit(4.8)
        self.filament['device'].output_status(True)
        self.bias = {}
        self.bias['device'] = smu.KeithleySMU(interface='lan', hostname='10.54.6.168')
        self.bias['grid_voltage'] = 0
        self.bias['grid_current'] = 0
        self.bias['device'].output_state(True)
        self.pid = pid.PID(0.01, 0.1, 0, 4)
        self.looptime = 0
        self.setpoint = 0.05
        self.pid.update_setpoint(self.setpoint)
        self.running = True
        self.wanted_voltage = 0
        self.emission_current = 999

    def set_bias(self, bias):
        """ Set the bias-voltage """
        if self.datasocket is not None:
            self.datasocket.set_point_now('ionenergy', bias)
        if bias > -1:
            self.bias['device'].set_voltage(bias)

    def update_setpoint(self, setpoint):
        """ Update the setpoint """
        self.setpoint = setpoint
        self.datasocket.set_point_now('setpoint', setpoint)
        self.livesocket.set_point_now('setpoint', setpoint)

    def set_filament_voltage(self, voltage):
        """ Set the filament voltage """
        return self.filament['device'].set_voltage(voltage)

    def read_filament_voltage(self):
        """ Read the filament voltage """
        return self.filament['device'].read_actual_voltage()

    def read_filament_current(self):
        """ Read the filament current """
        return self.filament['device'].read_actual_current()

    def read_grid_voltage(self):
        """Read the actual grid voltage """
        return self.bias['device'].read_voltage()

    def read_emission_current(self):
        """ Read the grid current as measured by power supply """
        return self.bias['device'].read_current() * 1000

    def read_grid_current(self):
        """ Read the actual emission current """
        return self.bias['device'].read_current()

    def value(self):
        """ Return the curren emission value """
        return self.emission_current

    def run(self):
        while self.running:
            #time.sleep(0.1)
            start_time = time.time()
            qsize = self.pushsocket.queue.qsize()
            LOGGER.debug('qsize: ' + str(qsize))
            while qsize > 0:
                element = self.pushsocket.queue.get()
                LOGGER.debug('Element: ' + str(element))
                param = element.keys()[0]
                if param == 'setpoint':
                    value = element[param]
                    self.update_setpoint(value) 
                qsize = self.pushsocket.queue.qsize()

            self.emission_current = self.read_emission_current()
            self.wanted_voltage = (self.pid.wanted_power(self.emission_current) + 
                                   self.filament['idle_voltage'])
            self.pid.update_setpoint(self.setpoint)
            self.set_filament_voltage(self.wanted_voltage)
            self.filament['voltage'] = self.read_filament_voltage()
            self.filament['current'] = self.read_filament_current()
            self.bias['grid_voltage'] = self.read_grid_voltage()
            self.bias['grid_current'] = self.read_grid_current()
            self.datasocket.set_point_now('emission', self.emission_current)
            self.livesocket.set_point_now('emission', self.emission_current)
            self.looptime = time.time() - start_time
        self.setpoint = 0
        self.set_filament_voltage(0)
        #self.set_bias(0)


if __name__ == '__main__':
    ec = EmissionControl()
    #ec.set_bias(35)
    ec.start()

    logger = ValueLogger(ec, comp_val = 1, comp_type='log')
    logger.start()

    CODENAMES = ['tof_emission_value']
    db_logger = ContinuousLogger(table='dateplots_tof',
                                 username=credentials.user,
                                 password=credentials.passwd,
                                 measurement_codenames=CODENAMES)
    db_logger.start()

    tui = emission_tui.CursesTui(ec)
    tui.daemon = True
    tui.start()
    time.sleep(10)

    while ec.running:
        time.sleep(1)
        value = logger.read_value()
        if logger.read_trigged():
            LOGGER.debug('Logged value: ' + str(value))
            db_logger.enqueue_point_now('tof_emission_value', value)
            logger.clear_trigged()

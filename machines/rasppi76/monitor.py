
"""I2C communication for the Large CO2 MEA setup

This program is responsible for making a socket available. The data
received on this socket will be writte to a DAC and is currently used
to set the value of pressure controllers. Meanwhile the program
continuously measures values from a ADC, which is presently used to
measure the voltage over the MEA and possibly also the state of the
pressure controllers.

"""

from queue import Queue, Empty
from time import sleep

from PyExpLabSys.drivers.microchip_tech_mcp3428 import MCP3428
from PyExpLabSys.drivers.analogdevices_ad5667 import AD5667
from PyExpLabSys.common.sockets import DataPushSocket

from PyExpLabSys.common.supported_versions import python3_only
python3_only(__file__)


class I2CComm(object):
    """Handle I2C communication with DAC and ADC"""

    def __init__(self):
        self.measurements = {}
        self.mcp3428 = MCP3428()
        self.ad5667 = AD5667()
        self.dps = DataPushSocket(
            'large_CO2_mea_push_socket',
            action='callback_direct',
            callback=self.communicate,
            return_format='json',
        )

        # These two queues form a pair, that is used to interrupt the
        # continuous measurement of the values from the ADC to allow
        # setting the DAC and return copy the values from the ADC
        self.comm_flag = Queue()
        self.comm_return = Queue()

        self.dps.start()

    def measure(self):
        """Main measure loop (busy)"""
        while True:
            for channel in range(1, 5):
                self.measurements[channel] = self.mcp3428.read_sample(channel)
            print("Measured:", self.measurements)

            try:
                values_to_set = self.comm_flag.get(block=False)
            except Empty:
                continue

            # If we escaped the comm_flag test, we should set and enqueue current values
            if "no_voltages_to_set" not in values_to_set:
                print("Asked to set DAC values", values_to_set)
                sleep(0.01)
                self.ad5667.set_channel_A(values_to_set['A'])
                self.ad5667.set_channel_B(values_to_set['B'])
                sleep(0.01)
            self.comm_return.put(dict(self.measurements))

    def run(self):
        """Run method used to allow keyboard interrupts"""
        try:
            self.measure()
        except KeyboardInterrupt:
            self.dps.stop()

    def communicate(self, data):
        """Send the received values to be written on the DAC and return values
        from the ADC

        """
        self.comm_flag.put(data)
        # Wait until we get values back
        result = self.comm_return.get()
        return result


def main():
    """Main function"""
    data_reader = I2CComm()
    data_reader.run()


main()

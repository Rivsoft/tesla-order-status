from typing import Any, Dict, Optional


class VinDecoder:
    def __init__(self):
        self.wmi_map = {
            "5YJ": "Tesla Inc. (USA) - Passenger",
            "7SA": "Tesla Inc. (USA) - MPV (Austin/Fremont)",
            "7G2": "Tesla Inc. (USA) - Truck",
            "LRW": "Tesla Inc. (China)",
            "XP7": "Tesla Inc. (Germany)",
            "SFZ": "Tesla Inc. (UK)",
        }

        self.model_map = {
            "S": "Model S",
            "3": "Model 3",
            "X": "Model X",
            "Y": "Model Y",
            "R": "Roadster",
            "T": "Semi",
            "C": "Cybertruck",
        }

        self.body_type_map = {
            "A": "Liftback / 5-door (Model S LHD)",
            "B": "Liftback / 5-door (Model S RHD)",
            "C": "SUV / MPV (Model X LHD)",
            "D": "SUV / MPV (Model X RHD)",
            "E": "Sedan / 4-door (Model 3 LHD)",
            "F": "Sedan / 4-door (Model 3 RHD)",
            "G": "Crossover SUV / 5-door (Model Y LHD)",
            "H": "Crossover SUV / 5-door (Model Y RHD)",
            "J": "Pickup / Light Duty (Cybertruck AWD)",
            "K": "Pickup / Light Duty (Cybertruck Tri-Motor)",
            "P": "Day-cab Tractor (Semi LHD)",
            "R": "Day-cab Tractor (Semi RHD)",
        }

        self.restraint_system_map = {
            "1": "Manual Type 2 Seatbelts (Front, Rear*3) with Front Airbags",
            "3": "Manual Type 2 Seatbelts (Front, Rear*2) with Front/Side Airbags",
            "4": "Manual Type 2 Seatbelts (Front, Rear*3) with Front/Side Airbags",
            "5": "Manual Type 2 Seatbelts (Front, Rear*2) with Front/Side Airbags",
            "6": "Manual Type 2 Seatbelts (Front, Rear*3) with Front/Side Airbags",
            "7": "Type 2 Seatbelts (Front, Rear*3) with Front Airbags & Side Inflatable Restraints",
            "A": "Manual Seatbelts (Front, Rear*3) with Front Airbags & Side Inflatable Restraints",
            "B": "Manual Seatbelts (Front, Rear*2) with Front Airbags & Side Inflatable Restraints",
            "C": "Manual Seatbelts (Front, Rear*3) with Front Airbags & Side Inflatable Restraints",
            "D": "Manual Seatbelts (Front, Rear*2) with Front Airbags & Side Inflatable Restraints",
            "H": "Manual Seatbelts (Front, Rear*3) with Front Airbags & Side Inflatable Restraints (Truck)",
        }

        self.battery_type_map = {
            "E": "Lithium Ion (Electric)",
            "F": "Lithium Iron Phosphate (LFP)",
            "H": "Lithium Ion - High Capacity",
            "S": "Lithium Ion - Standard",
            "V": "Lithium Ion - Ultra High Capacity",
        }

        self.motor_map = {
            "1": "Single Motor - Standard",
            "2": "Dual Motor - Standard",
            "3": "Single Motor - Performance",
            "4": "Dual Motor - Performance",
            "5": "Plaid (Tri Motor)",
            "6": "Triple Motor",
            "A": "Single Motor - Standard (3/Y)",
            "B": "Dual Motor - Standard (3/Y)",
            "C": "Dual Motor - Performance (3/Y)",
            "D": "Dual Motor - Standard (Truck/Cybertruck)",
            "E": "Dual Motor - Standard (Front/Rear)",
            "F": "Quad Motor",
            "J": "Single Motor (Highland)",
            "K": "Dual Motor (Highland)",
            "L": "Single Motor",
            "R": "Single Motor (Rear)",
            "S": "Single Motor (Standard)",
            "T": "Dual Motor (Highland/New)",
            "X": "Dual Motor (Cybertruck)",
            "Y": "Tri Motor (Cyberbeast)",
        }

        self.year_map = {
            # VIN year codes repeat every 30 years. This covers 2010-2039.
            "A": 2010,
            "B": 2011,
            "C": 2012,
            "D": 2013,
            "E": 2014,
            "F": 2015,
            "G": 2016,
            "H": 2017,
            "J": 2018,
            "K": 2019,
            "L": 2020,
            "M": 2021,
            "N": 2022,
            "P": 2023,
            "R": 2024,
            "S": 2025,
            "T": 2026,
            "V": 2027,
            "W": 2028,
            "X": 2029,
            "Y": 2030,
            "1": 2031,
            "2": 2032,
            "3": 2033,
            "4": 2034,
            "5": 2035,
            "6": 2036,
            "7": 2037,
            "8": 2038,
            "9": 2039,
        }

        self.plant_map = {
            "A": "Austin, Texas, USA",
            "B": "Berlin, Germany",
            "C": "Shanghai, China",
            "F": "Fremont, California, USA",
            "P": "Palo Alto, California, USA",
            "R": "Reno, Nevada, USA",
        }

    def decode(self, vin: str) -> Optional[Dict[str, Any]]:
        if not vin or len(vin) != 17:
            return None

        wmi = vin[:3]
        model_code = vin[3]
        body_code = vin[4]
        restraint_code = vin[5]
        battery_code = vin[6]
        motor_code = vin[7]
        check_digit = vin[8]
        year_code = vin[9]
        plant_code = vin[10]
        serial = vin[11:]

        return {
            "Manufacturer": self.wmi_map.get(wmi, "Unknown"),
            "Model": self.model_map.get(model_code, "Unknown"),
            "Body Type": self.body_type_map.get(body_code, "Unknown"),
            "Restraint System": self.restraint_system_map.get(
                restraint_code, "Unknown"
            ),
            "Battery Type": self.battery_type_map.get(battery_code, "Electric"),
            "Motor": self.motor_map.get(motor_code, "Unknown"),
            "Year": self.year_map.get(year_code, "Unknown"),
            "Factory": self.plant_map.get(plant_code, "Unknown"),
            "Serial Number": serial,
            "Check Digit": check_digit,
        }

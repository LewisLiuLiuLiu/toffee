"""Lightweight parser for ngspice binary raw files.

Implements the SPICE3f5 raw file format without external dependencies.
"""

import struct


class NgSpiceRawParser:
    """Parse ngspice ASCII/Binary raw output files."""

    def __init__(self, path: str):
        self.path = path
        self.title = ""
        self.date = ""
        self.plotname = ""
        self.flags = ""
        self.num_variables = 0
        self.num_points = 0
        self.variables = []  # [{"index": int, "name": str, "type": str}, ...]
        self._data = {}      # name -> scalar or list of values

    def parse(self) -> dict:
        """Parse the raw file and return a dict of variable_name -> values."""
        with open(self.path, "rb") as f:
            content = f.read()

        # Find the end of the ASCII header (blank line before Binary:)
        # The header ends with "Binary:\n"
        binary_marker = b"Binary:\n"
        marker_pos = content.find(binary_marker)
        if marker_pos == -1:
            # Try ASCII mode marker
            binary_marker = b"Values:\n"
            marker_pos = content.find(binary_marker)
            if marker_pos == -1:
                raise ValueError(f"Cannot find 'Binary:' or 'Values:' marker in {self.path}")
            is_binary = False
        else:
            is_binary = True

        header = content[:marker_pos].decode("ascii", errors="replace")
        payload = content[marker_pos + len(binary_marker):]

        self._parse_header(header)

        if is_binary:
            self._parse_binary(payload)
        else:
            self._parse_ascii(payload)

        # Expose as dict
        self._data = {}
        for var in self.variables:
            self._data[var["name"]] = var["data"]
        return self._data

    def _parse_header(self, header: str):
        lines = [line.rstrip("\r") for line in header.split("\n")]
        section = None

        for line in lines:
            if line.startswith("Title: "):
                self.title = line[7:]
            elif line.startswith("Date: "):
                self.date = line[6:]
            elif line.startswith("Plotname: "):
                self.plotname = line[10:]
            elif line.startswith("Flags: "):
                self.flags = line[7:].strip()
            elif line.startswith("No. Variables: "):
                self.num_variables = int(line[15:])
            elif line.startswith("No. Points: "):
                self.num_points = int(line[12:])
            elif line == "Variables:":
                section = "variables"
            elif section == "variables" and line.startswith("\t"):
                parts = line.strip().split("\t")
                # Format: index<tab>name<tab>type
                if len(parts) >= 3:
                    self.variables.append(
                        {
                            "index": int(parts[0]),
                            "name": parts[1],
                            "type": parts[2],
                            "data": [] if self.num_points > 1 else None,
                        }
                    )

    def _parse_binary(self, payload: bytes):
        if self.flags == "real":
            # Each point: N doubles (8 bytes each), little-endian
            fmt = "<" + "d" * self.num_variables
            point_size = struct.calcsize(fmt)
            expected_size = point_size * self.num_points
            if len(payload) < expected_size:
                raise ValueError(
                    f"Binary payload too short: got {len(payload)}, expected {expected_size}"
                )

            for i in range(self.num_points):
                offset = i * point_size
                point = struct.unpack_from(fmt, payload, offset)
                for j, var in enumerate(self.variables):
                    if self.num_points > 1:
                        var["data"].append(point[j])
                    else:
                        var["data"] = point[j]

        elif self.flags == "complex":
            # Each variable per point: two doubles (real, imag)
            fmt = "<" + "d" * (self.num_variables * 2)
            point_size = struct.calcsize(fmt)
            expected_size = point_size * self.num_points
            if len(payload) < expected_size:
                raise ValueError(
                    f"Binary payload too short: got {len(payload)}, expected {expected_size}"
                )

            for i in range(self.num_points):
                offset = i * point_size
                point = struct.unpack_from(fmt, payload, offset)
                for j, var in enumerate(self.variables):
                    real = point[j * 2]
                    imag = point[j * 2 + 1]
                    if self.num_points > 1:
                        var["data"].append(complex(real, imag))
                    else:
                        var["data"] = complex(real, imag)
        else:
            raise ValueError(f"Unsupported raw flags: {self.flags}")

    def _parse_ascii(self, payload: bytes):
        text = payload.decode("ascii", errors="replace")
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        point_idx = 0
        var_idx = 0
        for line in lines:
            if line.startswith("\t"):
                # data line: \tvalue
                value = float(line.strip())
                var = self.variables[var_idx]
                if self.num_points > 1:
                    var["data"].append(value)
                else:
                    var["data"] = value
                var_idx += 1
                if var_idx >= self.num_variables:
                    var_idx = 0
                    point_idx += 1
            else:
                # Some lines may be point indices in ASCII raw files
                pass

    def read(self, name: str):
        """Return the parsed data for a variable name.

        For single-point analyses (.op) returns a scalar.
        For multi-point analyses (.ac, .tran) returns a list.
        """
        if name not in self._data:
            raise KeyError(f"Variable '{name}' not found in raw file. Available: {list(self._data.keys())}")
        return self._data[name]

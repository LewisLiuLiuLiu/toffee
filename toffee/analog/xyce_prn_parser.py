"""Lightweight parser for Xyce ASCII .prn output files."""


class XycePrnParser:
    """Parse Xyce space-separated .prn files."""

    def __init__(self, path: str):
        self.path = path
        self.columns = []
        self.rows = []

    def parse(self):
        """Parse the file and populate columns / rows."""
        with open(self.path, "r") as f:
            lines = f.readlines()

        if not lines:
            raise ValueError(f"Empty PRN file: {self.path}")

        # First line: column headers
        self.columns = lines[0].strip().split()
        self.rows = []
        for line in lines[1:]:
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split()
            if len(parts) != len(self.columns):
                continue
            self.rows.append([float(p) for p in parts])

    def read_at_time(self, variable_name: str, target_time: float):
        """Return the value of *variable_name* at the row closest to *target_time*."""
        # Case-insensitive lookup since Xyce uppercases column headers
        var_upper = variable_name.upper()
        col_idx = None
        for i, col in enumerate(self.columns):
            if col.upper() == var_upper:
                col_idx = i
                break
        if col_idx is None:
            raise KeyError(
                f"Variable '{variable_name}' not in PRN. Available: {self.columns}"
            )
        time_idx = self.columns.index("TIME")

        best_val = None
        best_diff = float("inf")
        for row in self.rows:
            t = row[time_idx]
            diff = abs(t - target_time)
            if diff < best_diff:
                best_diff = diff
                best_val = row[col_idx]
        return best_val

    def read_latest(self, variable_name: str):
        """Return the last available value of *variable_name*."""
        var_upper = variable_name.upper()
        col_idx = None
        for i, col in enumerate(self.columns):
            if col.upper() == var_upper:
                col_idx = i
                break
        if col_idx is None:
            raise KeyError(
                f"Variable '{variable_name}' not in PRN. Available: {self.columns}"
            )
        if not self.rows:
            raise ValueError("No data rows in PRN file")
        return self.rows[-1][col_idx]

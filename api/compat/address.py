"""Address-text helpers shared by ports that match on "house number + street".

The frontend sends ``address`` as a comma-joined display string
("47, Montagu Avenue, Newcastle Upon Tyne, NE3 4JJ") plus the parts
``house_number`` ("47") and ``street`` ("Montagu Avenue"). Council sites that
search or match on text want the first line ("47 Montagu Avenue"), which is
better built from the parts than parsed out of the joined string.
"""


def first_line(address: str = "", house_number: str = "", street: str = "") -> str:
    """Return the "house number + street" first line for text matching.

    - house_number and street both given: ``"<house_number> <street>"``.
    - otherwise ``address`` if given (a bare first line such as "1 Grange Road"),
      else ``house_number`` alone (some fixtures pass the whole first line there).
    """
    house_number = (house_number or "").strip()
    street = (street or "").strip()
    if house_number and street:
        return f"{house_number} {street}"
    return (address or house_number).strip()

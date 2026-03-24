import asyncio

from api.services.address_lookup import AddressLookup


async def test():
    async with AddressLookup() as lookup:
        # Example postcode for Aberdeen (S12000033)
        postcode = "AB10 1AB"
        authority = await lookup.get_local_authority(postcode)
        print(f"Postcode: {postcode}")
        print(f"Authority: {authority}")

        # Example postcode for Adur (E07000223)
        postcode = "BN11 1AA"
        authority = await lookup.get_local_authority(postcode)
        print(f"Postcode: {postcode}")
        print(f"Authority: {authority}")

if __name__ == "__main__":
    asyncio.run(test())

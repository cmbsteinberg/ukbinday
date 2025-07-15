import polars as pl
import requests
from io import BytesIO
import zipfile

nspl_url = "https://www.arcgis.com/sharing/rest/content/items/077631e063eb4e1ab43575d01381ec33/data"
nspl_zip = requests.get(nspl_url)

zip_buffer = BytesIO(nspl_zip.content)

# Read CSV directly from zip
with zipfile.ZipFile(zip_buffer, "r") as zip_file:
    with zip_file.open("Data/NSPL_MAY_2025_UK.csv") as csv_file:
        postcodes_full = pl.read_csv(csv_file)

govuk_council_urls = "https://govuk-app-assets-production.s3.eu-west-1.amazonaws.com/data/local-links-manager/links_to_services_provided_by_local_authorities.csv"
la_urls = (
    pl.read_csv(govuk_council_urls)
    .select(["Authority Name", "GSS", "Description", "URL"])
    .filter(
        pl.col("Description").str.contains(
            "Household waste collection: Providing information"
        )
    )
)
postcodes = (
    postcodes_full.select(["pcd", "laua"])
    .group_by("laua")
    .agg(pl.col("pcd").sample(3).alias("sampled_pcds"))
    .with_columns(
        [
            pl.col("sampled_pcds").list.get(0).alias("pcd1"),
            pl.col("sampled_pcds").list.get(1).alias("pcd2"),
            pl.col("sampled_pcds").list.get(2).alias("pcd3"),
        ]
    )
    .drop("sampled_pcds")
)


joined_df = la_urls.join(postcodes, how="left", left_on="GSS", right_on="laua").select(
    ["Authority Name", "URL", "pcd1", "pcd2", "pcd3"]
)
joined_df.write_csv("../data/bins_info.csv")

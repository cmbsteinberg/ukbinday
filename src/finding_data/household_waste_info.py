import marimo

__generated_with = "0.14.11"
app = marimo.App(width="medium")


@app.cell
def _():
    import polars as pl
    import requests
    from io import BytesIO
    import zipfile

    return BytesIO, pl, requests, zipfile


@app.cell
def _(BytesIO, pl, requests, zipfile):
    def get_postcode_data(
        nspl_url="https://www.arcgis.com/sharing/rest/content/items/077631e063eb4e1ab43575d01381ec33/data",
    ) -> pl.DataFrame:
        """
        Downloads and extracts the latest National Statistics Postcode Lookup (NSPL) data.
        """
        print("Downloading NSPL postcode data...")
        nspl_zip = requests.get(nspl_url)
        zip_buffer = BytesIO(nspl_zip.content)
        print("Download complete.")

        with zipfile.ZipFile(zip_buffer, "r") as zip_file:
            # Find the UK-wide CSV file, which is the largest CSV in the 'Data' folder
            csv_file_name = max(
                (
                    f
                    for f in zip_file.infolist()
                    if f.filename.startswith("Data/") and f.filename.endswith(".csv")
                ),
                key=lambda f: f.file_size,
            ).filename

            print(f"Reading from: {csv_file_name}")
            with zip_file.open(csv_file_name) as csv_file:
                # Select only the necessary columns to reduce memory usage
                postcodes_full = pl.read_csv(
                    csv_file, columns=["pcd", "laua"]
                ).with_columns(pl.col("pcd").str.replace_all(" ", "").alias("pcd"))

        return postcodes_full

    return (get_postcode_data,)


@app.cell
def _(pl):
    def get_council_urls(
        govuk_council_urls="https://govuk-app-assets-production.s3.eu-west-1.amazonaws.com/data/local-links-manager/links_to_services_provided_by_local_authorities.csv",
    ) -> pl.DataFrame:
        """
        Fetches council service URLs from GOV.UK.
        """
        print("Fetching council waste collection URLs...")
        la_urls = (
            pl.read_csv(govuk_council_urls)
            .select(
                ["Authority Name", "GSS", "Description", "URL"],
            )
            .filter(
                pl.col("Description").str.contains(
                    "Household waste collection: Providing information"
                )
            )
            .drop("Description")  # No longer needed after filtering
        )
        return la_urls

    return (get_council_urls,)


@app.cell
def _(pl, requests):
    def get_pop_data(
        eng_wales_postcode_pop_url="https://www.nomisweb.co.uk/output/census/2021/pcd_p002.csv",
        scotland_postcode_pop_url="https://www.nrscotland.gov.uk/media/mafbfvmj/postcode2022_usualresidentpopulation.csv",
        ni_postcode_pop_url="https://www.nisra.gov.uk/system/files/statistics/census-2021-person-and-household-estimates-for-postcodes-in-northern-ireland.xlsx",
    ):
        scotland_postcode_get = requests.get(scotland_postcode_pop_url)
        scotland_postcode_pop = pl.read_csv(scotland_postcode_get.content).select(
            pl.col("Postcode").cast(pl.String).alias("postcode"),
            pl.col("UsualResidentPopulation")
            .cast(pl.Int64, strict=False)
            .alias("population"),
        )

        eng_wales_pop = pl.read_csv(eng_wales_postcode_pop_url).select(
            pl.col("Postcode").cast(pl.String).alias("postcode"),
            pl.col("Count").cast(pl.Int64, strict=False).alias("population"),
        )

        ni_postcode_pop = (
            pl.read_excel(
                ni_postcode_pop_url,
                sheet_name="Postcode",
                columns=[0, 4],
                has_header=False,
            )
            .slice(6)
            .select(
                pl.col("column_1").cast(pl.String).alias("postcode"),
                pl.col("column_2").cast(pl.Int64, strict=False).alias("population"),
            )
        )
        combined_df = (
            pl.concat(
                [
                    scotland_postcode_pop,
                    eng_wales_pop,
                    ni_postcode_pop,
                ]
            )
            .drop_nulls()
            .with_columns(pl.col("postcode").str.replace_all(" ", "").alias("pcd"))
        )
        return combined_df

    return (get_pop_data,)


@app.cell
def _(get_pop_data, get_postcode_data):
    def get_populous_postcodes():
        # 1. Get the raw postcode data
        postcode_df = get_postcode_data()
        postcode_pop = get_pop_data()

        postcode_merge = postcode_df.join(
            postcode_pop, how="inner", left_on="pcd", right_on="pcd"
        ).drop("pcd")

        return postcode_merge

    return (get_populous_postcodes,)


@app.cell
def _(get_council_urls, get_populous_postcodes, pl):
    def main(output_filename="data/postcodes_by_council.csv"):
        postcode_merge = get_populous_postcodes()
        # 2. Get the council URL data
        council_urls_df = get_council_urls()

        # 3. Merge the two DataFrames before analysis
        # This joins the council name and URL to each postcode
        print("Merging postcode and council URL data...")
        merged_df = (
            council_urls_df.join(
                postcode_merge, left_on="GSS", right_on="laua", how="left"
            )
            .group_by("Authority Name", "URL")
            .agg(
                [
                    pl.col("postcode")
                    .filter(pl.col("population") >= pl.col("population").quantile(0.75))
                    .first()
                    .alias("postcode"),
                ]
            )
        )

        # 6. Save the final enriched data to a CSV
        # This file will contain all postcodes with their analysis and council info
        print(f"\nWriting full analyzed data to {output_filename}...")
        merged_df.write_csv(output_filename)
        print("Done.")

        return merged_df

    return (main,)


@app.cell
def _(main):
    output = main()
    return


if __name__ == "__main__":
    app.run()

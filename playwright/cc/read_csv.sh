#!/bin/bash

# Define the file path
FILE="/Users/christophersteinberg/Documents/GitHub/bins/data/postcodes_by_council.csv"

# Check if the file exists
if [ -f "$FILE" ]; then
    echo "Reading the first lines of $FILE:"
    (head -n 1 "$FILE"; tail -n +4 "$FILE") | head -n 13
else
    echo "Error: File $FILE not found."
fi
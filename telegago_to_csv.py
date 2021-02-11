import csv
import channels
import pandas as pd
from channels import search_channels_telegago
from channels import parse_telegago_page
srch = "Navalny" #"Навальный"
results = search_channels_telegago(srch)
f = open('test.csv', 'a+')
with f:

    writer = csv.writer(f)
    writer.writerow(results)


df = pd.read_csv('test.csv')
df = df.T.reset_index()
df = df.rename(columns = {'index' : 'names'})
df["names"].to_csv('channels_to_add.csv', index=False, header=False)
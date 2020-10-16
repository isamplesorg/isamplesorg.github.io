Counting Registered IGSNs
=========================

This page counts the number of IGSN registrations by year and by OAI-PMH set.


.. jupyter-execute::

    import igsn_lib.oai
    import logging
    import pandas as pd
    import numpy as np

    baseurl = "https://doidb.wdc-terra.org/igsnoaip/oai"

    # Get a list of sets from the OAI-PMH service
    svc = igsn_lib.oai.getSickle(baseurl)
    set_list = igsn_lib.oai.listSets(svc, get_counts=False)
    base_names = set()
    for s in set_list:
        parts = s['setSpec'].split(".",1)
        base_names.add(parts[0])
    base_names = sorted(base_names)
    print(' '.join(base_names))


.. jupyter-execute::

    import concurrent.futures
    import time

    def loadCount(service, bname, year):
        dfrom = f"{year}-01-01T00:00:00Z"
        duntil = f"{year+1}-01-01T00:00:00Z"
        count = igsn_lib.oai.recordCount(service, setSpec=bname, tfrom=dfrom, tuntil=duntil)
        return (bname, year, count, )

    years = [2012,2013,2014,2015,2016,2017,2018,2019,2020]
    columns = ['Registrant', 'Year', 'Count', ]
    data = []
    tstart = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = []
        for bname in base_names:
            for cyear in years:
                futures.append(executor.submit(loadCount, svc, bname, cyear))
        for future in concurrent.futures.as_completed(futures):
            row = future.result()
            data.append(row)
    df = pd.DataFrame.from_records(data, columns=columns)
    print(f"Took {time.time()-tstart}sec")

.. jupyter-execute::

    p = df.pivot(index='Registrant', columns='Year', values='Count')
    p['Total'] = p.sum(axis=1)
    p.loc['Total'] = p.sum()
    p


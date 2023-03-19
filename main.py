import streamlit as st
import pandas as pd
import PyPDF2
import numpy as np
from io import BytesIO
from datetime import datetime, date
import pdfplumber
import plotly.express as px
from plotly import graph_objects as go
import tabula
import re
import plotly_express as px

def extract(page, first_string, occurence, start, end):
    get = data_text[page].split(first_string)[occurence][start:end]
    trim = get.lstrip()
    return trim

def extract_number(page, first_string, occurence, start, end):
    get = data_text[page].split(first_string)[occurence][start:end]
    trim = get.lstrip()
    value = np.where(
        trim.__contains__('-'), 
        float(trim[:-1].replace(',','.'))*(-1), 
        (trim.replace(',','.'))
        ).item(0)
    return value

def to_excel(df):
    output = BytesIO()
    writer = pd.ExcelWriter(output, engine='xlsxwriter')
    df.to_excel(writer, index=False, sheet_name= 'Daten')
    workbook = writer.book
    workbook.formats[0].set_font_name('Helvetica')
    workbook.formats[0].set_border(2)
    worksheet = writer.sheets['Daten']
    worksheet.autofilter(0, 0, df.shape[0], df.shape[1]-1) # activate filter on column headers
    header_format = workbook.add_format({ # define header format
            'bold': True,
            'text_wrap': True,
            'valign': 'top',
            'fg_color': '#006E9D',
            'font_color': 'white',
            'border': 0,
            'font_name': 'Helvetica'
            })
    for idx, col in enumerate(df):  # loop through all columns
            series = df[col]
            max_len = max(
                series.astype(str).map(len).max(),  # len of largest item
                len(str(series.name))  # len of column name/header
                ) + 5  # adding more space
            worksheet.set_column(idx, idx, max_len)  # set column width
            for col_num, value in enumerate(df.columns.values):
                worksheet.write(0, col_num, value, header_format) # set header format
    format1 = workbook.add_format({'num_format': '0.00'}) 
    worksheet.set_column('A:A', None, format1)  
    writer.save()
    processed_data = output.getvalue()
    return processed_data

def to_csv(df):
    return df.to_csv(index=False).encode('utf-8')

def unique_cols(df):
    a = df.to_numpy() # df.values (pandas<0.24)
    return (a[0] == a).all(0)

@st.cache_data(show_spinner=False)
def get_data(source):
    dfs = []
    p = st.empty()
    for i, file in enumerate(source):
        p.progress((i+1)/len(source))

        tables = tabula.read_pdf(file, pages = "all", multiple_tables = True)

        # Zwei Seiten müssen für alle Zeitnachweise hinkommen
        df_1 = pd.DataFrame(tables[1])                  # Tabelle der ersten Seite
        df_1.drop(df_1.index[-1], inplace=True)         # lösche letzte Zeile
        df_2 = pd.DataFrame(tables[2])                  # Tabelle der zweiten Seite
        df_2.drop(df_2.index[-1], inplace=True)         # lösche letzte Zeile
        df_3 = pd.concat([df_1,df_2])                   # Zusammenführung beider Tabellen
        # Zusammenfügen beider Zeilen der Tabellen zu einer Zeile
        result = df_3.iloc[0].astype(str).str.cat(df_3.iloc[1].astype(str), sep='\r')
        df = pd.DataFrame(result).transpose()
        # Umbennenungen
        df = df.rename(columns={
            'Unnamed: 0':'Kommt & Geht',
            'Kommt\rUhrz.     Term.':'Ist-Zeit',
            'Geht\rUhrz.     Term.':'Über-Zeit',
            'Pause':'Sollzeit',
            'Ist-\rZeit':'Pause',
            'Über-\rZeit':'anrech. Istzeit',
            'anrech.\rIstzeit':'Zeit-Saldo',
            'Soll-\rzeit':'Mehrzeit Grundst.',
            'Zeit-\rSaldo':'Zuschlag'
            })
        # entferne leere Spalten
        df = df.drop(columns=['Mehrzeit\rGrundst.', 'Zuschl.'])
        # String zu Liste transformieren
        for col in df.columns:
            df[col].iloc[0] = df[col].str.split("\r").iloc[0]
        # Index aktualisieren
        df.reset_index(inplace=True)
        df.drop(columns=['index'], inplace=True)
        # Meistens müssen die zwei aufeinanderfolgenden Elemenete für Zeitstempelpaare zusammengeführt werden, es sei denn die Pause wurde nicht ausgebucht 
        condition = lambda x: x.startswith(('07', '08', '09', '10'))
        condition_2 = lambda x: x.startswith(('1', '0'))
        my_list = df['Kommt & Geht'].iloc[0]
        new_list = []
        temp = my_list[0]
        for i in range(1, len(my_list)):
            if condition(my_list[i]) or not condition_2(my_list[i]):
                new_list.append(temp)
                temp = my_list[i]
            else:
                temp += my_list[i]
        new_list.append(temp)
        df['Kommt & Geht'].iloc[0]=new_list
        # Bei Feiertagen werden keine zugehörigen Zeilen hinzugefügt, hier füge ich dafür nan Werte ein
        for count, val in enumerate(df['Kommt & Geht'].iloc[0]):
            if not val.startswith(('1', '0')) and not val=='Urlaub':
                df['Ist-Zeit'].iloc[0].insert(count, np.nan)
                df['Über-Zeit'].iloc[0].insert(count, np.nan)
                df['Pause'].iloc[0].insert(count, np.nan)
                df['anrech. Istzeit'].iloc[0].insert(count, np.nan)
                df['Sollzeit'].iloc[0].insert(count, np.nan)
                df['Zeit-Saldo'].iloc[0].insert(count, np.nan)
                df['Mehrzeit Grundst.'].iloc[0].insert(count, np.nan)
                df['Zuschlag'].iloc[0].insert(count, np.nan)
            if not val.startswith(('1', '0')):
                df['Kommt & Geht'].iloc[0][count] = '00:0000:00'
        # Zellen mit Listen in Zeilen exploden
        df = df.explode(column=['Tag', 'Kommt & Geht', 'Ist-Zeit', 'Über-Zeit', 'Pause', 'anrech. Istzeit', 'Sollzeit', 'Zeit-Saldo', 'Mehrzeit Grundst.', 'Zuschlag'])
        # Spalten 'regexen'
        df['Büro'] = np.where(df['Kommt & Geht'].str.contains('H'), 'Büro', 'Home-Office')
        df['Kommt'] = df['Kommt & Geht'].str.slice(stop=5)
        df['Kommt'] = pd.to_datetime(df['Kommt'], format='%H:%M')#.dt.time
        df['zeit'] = df['Kommt & Geht'].apply(lambda x: re.sub('H.{4}', '1', x) if 'H' in x else x)
        df['zeit'] = df['zeit'].apply(lambda x: re.sub('H.{4}', '1', x).replace(x[x.find('H'):x.find('H')+4],''))
        df['Geht'] = df['zeit'].str.slice(start=-5)
        df['Geht'] = pd.to_datetime(df['Geht'], format='%H:%M')#.dt.time
        df['Pause-Anfang'] = df['zeit'].apply(lambda x: x[5:10])
        df['Pause-Anfang'] = np.where( df['Pause-Anfang'] == df['zeit'].str.slice(start=-5), None, df['Pause-Anfang'])
        df['Pause-Anfang'] = pd.to_datetime(df['Pause-Anfang'], format='%H:%M')#.dt.time
        df['Pause-Ende'] = df['zeit'].apply(lambda x: x[10:15])
        df['Pause-Ende'] = np.where( df['Pause-Ende'] == '', None, df['Pause-Ende'])
        df['Pause-Ende'] = pd.to_datetime(df['Pause-Ende'], format='%H:%M')#.dt.time
        df['Gesamt-Zeit'] = (df['Geht'] - df['Kommt']) / pd.to_timedelta(1, unit='H')
        df['Vormittag-Zeit'] = (df['Pause-Anfang'] - df['Kommt']) / pd.to_timedelta(1, unit='H')
        df['Pausen-Dauer'] = (df['Pause-Ende'] - df['Pause-Anfang']) / pd.to_timedelta(1, unit='H')
        df['Nachmittag-Zeit'] = (df['Geht'] - df['Pause-Ende']) / pd.to_timedelta(1, unit='H')
        df['Datum'] = [datetime(int(tables[3].columns[0][-4:]), int(tables[3].columns[0][-7:-5]), int(d[:2])) for d in df['Tag'] ]
        df['Wochentag'] = df['Tag'].apply(lambda x: x[2:])
        df['Kommt'] = df['Kommt'].dt.time
        df['Geht'] = df['Geht'].dt.time
        df['Pause-Anfang'] = df['Pause-Anfang'].dt.time
        df['Pause-Ende'] = df['Pause-Ende'].dt.time
        df['Datum'] = df['Datum'].dt.date
        # Zahlen im String formatieren
        df['Ist-Zeit'] = [str(d).replace(',','.') for d in df['Ist-Zeit']]
        df['Über-Zeit'] = [str(d).replace(',','.') for d in df['Über-Zeit']]
        df['Pause'] = [str(d).replace(',','.') for d in df['Pause']]
        df['anrech. Istzeit'] = [str(d).replace(',','.') for d in df['anrech. Istzeit']]
        df['Sollzeit'] = [str(d).replace(',','.') for d in df['Sollzeit']]
        df['Mehrzeit Grundst.'] = [str(d).replace(',','.') for d in df['Mehrzeit Grundst.']]
        df['Zuschlag'] = [str(d).replace(',','.') for d in df['Zuschlag']]
        df['Zeit-Saldo'] = np.where(
            [str(d).__contains__('-') for d in df['Zeit-Saldo']],
            [('-'+str(d).replace('-','').replace(',','.')) for d in df['Zeit-Saldo']],
            [(str(d).replace(',','.')) for d in df['Zeit-Saldo']]
        ).astype(float)
        # Zwischenzeit nach Arbeitstagen, Urlaub und Feiertagen unterscheiden
        df['Arbeitstag'] = np.where( df['Ist-Zeit']=='nan', 'Feiertag', np.where( df['Gesamt-Zeit']==0, 'Urlaub', 'Arbeitstag'))  #df['Ist-Zeit'].map(type)==float
        # Zahlen als Float formatieren
        df['Ist-Zeit'] = [float(str(d).replace('nan','0')) for d in df['Ist-Zeit']]
        df['Über-Zeit'] = [float(str(d).replace('nan','0')) for d in df['Über-Zeit']]
        df['Pause'] = [float(str(d).replace('nan','0')) for d in df['Pause']]
        df['anrech. Istzeit'] = [float(str(d).replace('nan','0')) for d in df['anrech. Istzeit']]
        df['Sollzeit'] = [float(str(d).replace('nan','0')) for d in df['Sollzeit']]
        df['Mehrzeit Grundst.'] = [float(str(d).replace('nan','0')) for d in df['Mehrzeit Grundst.']]
        df['Zuschlag'] = [float(str(d).replace('nan','0')) for d in df['Zuschlag']]
        df['Pause-Gesamt'] = df['Pausen-Dauer']+df['Pause']
        # unnötige Spalten droppen
        df.drop(columns=['Tag', 'zeit', 'Kommt & Geht'],inplace=True)
        dfs.append(df)
    dfs = pd.concat(dfs)
    return dfs

def get_mean_time(series):
    value = pd.to_datetime([datetime.combine(date(1998, 11, 2), d) for d in series]).mean()
    string = str(value)[11:16]
    return string

@st.cache_data(show_spinner=False)
def get_meta_data(source):
    result = pd.DataFrame(columns= [ '/Author', '/CreationDate', '/Creator', '/Producer'])
    for uploaded_file in source:
        reader = PyPDF2.PdfReader(uploaded_file)
        num_pages = len(reader.pages) 
        data_text = []
        for page_num in range(num_pages):
            page = reader.pages[page_num]
            data_text.append(page.extract_text())
        
        meta = reader.metadata
        meta_dict = dict(meta)
        index = range(len(meta_dict))
        df = pd.DataFrame(meta_dict, index=index).drop_duplicates()
        df['Zeitraum von'] = pd.to_datetime(data_text[0].split("Zeitraum")[1][2:12])
        df['Zeitraum von'] = df['Zeitraum von'].dt.date
        df['Zeitraum bis'] = pd.to_datetime(data_text[0].split("Zeitraum")[1][15:25])
        df['Zeitraum bis'] = df['Zeitraum bis'].dt.date
        df['Personalnummer'] = data_text[0].split("Personalnummer")[1][2:10]
        df['Personalbereich'] = data_text[0].split("Personalbereich")[1][2:7]
        df['Teilbereich'] = data_text[0].split("Teilbereich")[1][2:6]
        df['Mitarbeiterkreis'] = data_text[0].split("Mitarbeiterkreis")[1][2:20]
        df['Kostenstelle'] = data_text[0].split("Kostenstelle")[1][2:12]
        df['Org.-Einheit'] = data_text[0].split("Org.-Einheit")[1][2:8]
        df['Arbeitszeitplan'] = data_text[0].split("Arbeitszeitplan")[1][2:7]
        df['Anteil %'] = float(data_text[0].split("Anteil %")[1][2:7].replace(',','.'))
        df['Status'] = data_text[0].split("Status")[1][2:20]
        df['Anzahl Seiten'] = len(reader.pages)
        df['Monatsübersicht zum Stichtag'] = data_text[1].split("Monatsübersicht zum Stichtag")[1][1:11]
        df['anrechenbare Istzeit'] = float(data_text[1].split("anrechenbare Istzeit")[1][3:9].replace(',','.'))
        df['Sollzeit'] = float(data_text[1].split("Sollzeit")[1][3:9].replace(',','.'))
        df['Zeit-Saldo akt.Periode'] = data_text[1].split("Zeit-Saldo akt.Periode")[1][3:10]
        df['Zeit-Saldo Vorperiode'] = data_text[1].split("Zeit-Saldo Vorperiode")[1][3:10]
        df['Zeit-Saldo zur Auszahlung'] = float(data_text[1].split("Zeit-Saldo zur Auszahlung")[1][3:10].replace(',','.'))
        df['Zeit-Saldo gesamt'] = data_text[1].split("Zeit-Saldo gesamt")[1][3:10]
        df['Überzeiten'] = float(data_text[1].split("Überzeiten")[1][3:9].replace(',','.'))
        df['Überzeit (Tag>10 Std.)'] = float(data_text[1].split("Überzeit (Tag>10 Std.)")[1][3:9].replace(',','.'))
        df['Überzeit außerhalb der Rahmenzeit'] = float(data_text[1].split("Überzeit außerhalb der Rahmenzeit")[1][3:9].replace(',','.'))
        df['Mehrarbeit Grundstunden'] = float(data_text[1].split("Mehrarbeit Grundstunden")[1][3:9].replace(',','.'))
        df['Mehrarbeit Zuschlag normal'] = float(data_text[1].split("Mehrarbeit Zuschlag normal")[1][3:9].replace(',','.'))
        df['Mehrarbeit Zuschlag Samstag'] = float(data_text[1].split("Mehrarbeit Zuschlag Samstag")[1][3:9].replace(',','.'))
        df['Mehrarbeit Zuschlag Sonntag'] = float(data_text[1].split("Mehrarbeit Zuschlag Sonntag")[1][3:9].replace(',','.'))
        df['Mehrarbeit Zuschlag Feiertag'] = float(data_text[1].split("Mehrarbeit Zuschlag Feiertag")[1][3:9].replace(',','.'))
        df['Nachtzuschlag'] = float(data_text[1].split("Nachtzuschlag")[1][3:9].replace(',','.'))
        df['Mehrarbeitskonto /Freizeit'] = float(data_text[1].split("Mehrarbeitskonto /Freizeit")[1][3:9].replace(',','.'))
        df['Resturlaub in Tagen'] = float(data_text[1].split("Resturlaub")[1][3:9].replace(',','.'))
        df['Zeit-Saldo akt.Periode'] = np.where(
            [str(d).__contains__('-') for d in df['Zeit-Saldo akt.Periode']],
            [('-'+str(d).replace('-','').replace(',','.').replace(' ','')) for d in df['Zeit-Saldo akt.Periode']],
            [(str(d).replace(',','.').replace(' ','')) for d in df['Zeit-Saldo akt.Periode']]).astype(float)
        df['Zeit-Saldo Vorperiode'] = np.where(
            [str(d).__contains__('-') for d in df['Zeit-Saldo Vorperiode']],
            [('-'+str(d).replace('-','').replace(',','.').replace(' ','')) for d in df['Zeit-Saldo Vorperiode']],
            [(str(d).replace(',','.').replace(' ','')) for d in df['Zeit-Saldo Vorperiode']]).astype(float)
        df['Zeit-Saldo gesamt'] = np.where(
            [str(d).__contains__('-') for d in df['Zeit-Saldo gesamt']],
            [('-'+str(d).replace('-','').replace(',','.').replace(' ','')) for d in df['Zeit-Saldo gesamt']],
            [(str(d).replace(',','.').replace(' ','')) for d in df['Zeit-Saldo gesamt']]).astype(float)
        result = pd.concat([result, df])
        result.drop(columns= [ '/Author', '/CreationDate', '/Creator', '/Producer'], inplace=True)        
        result.index = np.arange(1, len(result) + 1)
    return result

df = pd.DataFrame()


st.title('PDF-Dateien zu Datensatz zusammenfassen')
st.caption('Özgün Cakir, oezguen.cakir@axa.de')
st.error('diese Seite ist nicht fertig!')

st.header('Entgelabrechnungen')
uploaded_files_entg = st.file_uploader("Lade deine Entgeltabrechnungen hoch", accept_multiple_files=True)
result = pd.DataFrame(columns= [ '/Author', '/CreationDate', '/Creator', '/Producer'])
for uploaded_file in uploaded_files_entg:
    reader = PyPDF2.PdfReader(uploaded_file)
    num_pages = len(reader.pages) 
    data_text = []
    for page_num in range(num_pages):
        page = reader.pages[page_num]
        data_text.append(page.extract_text())
    
    meta = reader.metadata
    meta_dict = dict(meta)
    index = range(len(meta_dict))
    df = pd.DataFrame(meta_dict, index=index)
    #st.write(data_text[0])
    #st.write(data_text[1])
    df['Monat'] = data_text[0].split("Monat:")[1][1:10]
    df['Datum'] = datetime.strptime(data_text[0].split("Monat:")[1][1:10], '%m / %Y')
    
    df['Anzahl Seiten'] = len(reader.pages)
    df['Personalnr.'] = data_text[0].split("Personalnr.")[1][2:10]
    df['Geburtsdatum'] = data_text[0].split("Geburtsdatum")[1][2:12]
    df['Eintritt'] = data_text[0].split("Eintritt")[1][2:12]
    df['Kostenstelle'] = data_text[0].split("Kostenstelle")[1][2:12]
    df['Tarifgr./-stufe'] = data_text[0].split("Tarifgr./-stufe")[1][2:data_text[0].split("Tarifgr./-stufe")[1][2:].find('Geburtsdatum')+1]
    df['Steuerklasse'] = data_text[0].split("Steuerklasse")[1][2:4]
    df['Kinderfreibetr.'] = data_text[0].split("Kinderfreibetr.")[1][2:data_text[0].split("Kinderfreibetr.")[1][2:].find('Kon')] #passt
    df['Konfession'] = data_text[0].split("Konfession")[1][2:data_text[0].split("Konfession")[1][2:].find('Fre')]
    df['Freibetrag (Jahr/Monat)'] = data_text[0].split("Freibetrag (Jahr/Monat)")[1][2:data_text[0].split("Freibetrag (Jahr/Monat)")[1][2:].find('H')]
    df['SV-/Steuertage'] = data_text[0].split("SV-/Steuertage")[1][2:9]
    df['Hinzurechnungsb. (Jahr/Monat)'] = data_text[0].split("Hinzurechnungsb. (Jahr/Monat)")[1][2:data_text[0].split("Hinzurechnungsb. (Jahr/Monat)")[1][2:].find('RV')]
    df['RV-Nummer'] = data_text[0].split("RV-Nummer")[1][2:data_text[0].split("RV-Nummer")[1][2:].find(' ')+2]
    df['Krankenkasse'] = data_text[0].split("Krankenkasse")[1][2:data_text[0].split("Krankenkasse")[1][2:].find('SV-/St')]
    df['SV-Schlüssel'] = data_text[0].split("SV-Schlüssel")[1][2:data_text[0].split("SV-Schlüssel")[1][2:].find(' ')+2]
    df['KV / RV / AV / PV (in %)'] = data_text[0].split("Steuertage")[1][11:data_text[0].split("Steuertage")[1][11:].find('K')+11]

    #df['Kostenstelle'] = data_text[0].split("Kostenstelle")[1][2:].find(' ')

    df_obj = df.select_dtypes(['object'])
    df[df_obj.columns] = df_obj.apply(lambda x: x.str.strip())
    result = pd.concat([result, df])
result_2 = pd.DataFrame()
for uploaded_file in uploaded_files_entg:
    pdf = pdfplumber.open(uploaded_file)
    data_text_2 = []
    for page in pdf.pages:
        content = page.extract_text().split('Jahreswert')[1][1:].replace('Erläuterungen zu den verwendeten Abkürzungen: (E)inmalzahlungen, (L)ohnsteuer-, (S)V-pflichtig, (G)esamtbrutto','')
        data_text_2.append(content)
    df_2 = pd.DataFrame()
    df_2['Tarifgehalt'] = 11
    result_2 = pd.concat([result_2, df_2])
if uploaded_files_entg!=[]:
    result.drop(columns= [ '/Author', '/CreationDate', '/Creator', '/Producer'], inplace=True)
    result.sort_values('Datum', inplace= True)
    result.drop_duplicates(inplace=True)
    result.index = np.arange(1, len(result) + 1)

    st.write(result)

    st.download_button(
        label='📥 Download als Excel-Datei',
        data=to_excel(result),
        file_name= 'Entgeltnachweise.xlsx'
        )
    st.download_button(
        label="📥 Download als CSV-Datei", data=to_csv(result), 
        file_name="Entgeltnachweise.csv", 
        mime="text/csv"
        )
    

    st.subheader('Seit deinem Eintritt')
    eintrittsdatum = datetime.strptime(result['Eintritt'].iloc[0], "%d.%m.%Y").date()
    geburtsdatum = datetime.strptime(result['Geburtsdatum'].iloc[0], "%d.%m.%Y").date()
    heute = date.today()
    dauer_seit_eintritt = heute - eintrittsdatum
    dauer_seit_geburt = heute - geburtsdatum
    col1, col2, col3 = st.columns(3)
    col1.metric('Jahre', str(round(dauer_seit_eintritt.days/365.25,1)).replace('.',','))
    col2.metric('Monate', str(round(dauer_seit_eintritt.days/30.4375,1)).replace('.',','))
    col3.metric('Tage', str(dauer_seit_eintritt.days))

    
    st.info(str("{:.1%}".format(dauer_seit_eintritt.days/dauer_seit_geburt.days)).replace('.',',') + ' deiner Lebenszeit hast du bei der AXA verbracht')


    if int(result['RV-Nummer'].iloc[0][9:11]) < 50:
        st.write('Du bist männlich')
    else:
        st.write('Du bist weiblich')


st.header('Zeitnachweise')
uploaded_files_zeit = st.file_uploader("Lade deine Zeitnachweise hoch", accept_multiple_files=True)
if uploaded_files_zeit != []:

    # DATENZIEHUNG
    result2 = get_meta_data(uploaded_files_zeit)
    dfs = get_data(uploaded_files_zeit) 
    main_df = dfs[dfs['Arbeitstag']=='Arbeitstag'].reset_index().drop(columns='index') #.set_index('Datum')
    main_df.index = main_df.index + 1


    # METADATEN
    st.subheader('Metadaten')
    radio_spalten = st.radio(label='Anzuzeigende Spalten', options=['alle Spalten','Spalten - alle Werte gleich', 'Spalten - nicht alle Werte gleich'], horizontal=True)
    if radio_spalten == 'alle Spalten':
        result2 = result2
    elif radio_spalten == 'Spalten - alle Werte gleich':
        result2 = result2[result2.columns[result2.apply(unique_cols)]]
    elif radio_spalten == 'Spalten - nicht alle Werte gleich':
        result2 = result2[result2.columns[~result2.apply(unique_cols)]]
    st.write(result2)
    col1,col2=st.columns(2)
    col1.download_button(label='📥 Download als Excel-Datei', data=to_excel(result2), file_name= 'Zeitnachweise_Zusammenfassung.xlsx')
    col2.download_button(label="📥 Download als CSV-Datei", data=to_csv(result2), file_name="Zeitnachweise_Zusammenfassung.csv", mime="text/csv")


    # DATENSATZ
    st.subheader('Der Datensatz')
    st.write(main_df)
    col1,col2=st.columns(2)
    col1.download_button(label='📥 Download als Excel-Datei', data=to_excel(main_df), file_name= 'Zeitnachweise.xlsx')
    col2.download_button(label="📥 Download als CSV-Datei", data=to_csv(main_df), file_name="Zeitnachweise.csv", mime="text/csv")


    # ZEITRAUM
    st.subheader('Zeitraum')
    col1,col2,col3 = st.columns(3)
    col1.metric('erster Tag', str(dfs['Datum'].min()))
    col2.metric('letzter Tag', str(dfs['Datum'].max()))
    col3.metric('Tage dazwischen', (dfs['Datum'].max() - dfs['Datum'].min()).days)
    num_weekends = (dfs['Datum'].max() - dfs['Datum'].min()).days - len(dfs)
    num_workdays = len(main_df)
    num_vacation = len(dfs[dfs['Arbeitstag']=='Urlaub'])
    num_holidays = len(dfs[dfs['Arbeitstag']=='Feiertag'])
    st.info('An ' + "{0:.0%}".format(num_workdays/(len(dfs)+num_weekends)) + ' der Tage hast du gearbeitet')
    fig = px.pie(
        dfs,
        names=['Arbeitstag', 'Wochenende', 'Urlaub', 'Feiertag'],
        values=[num_workdays, num_weekends, num_vacation, num_holidays],
        color_discrete_sequence=['#0068C9', '#00A0E7', '#00D0E0', '#70FACB'])
    fig.update_traces(textposition='inside', textinfo='value+label')
    st.plotly_chart(fig, use_container_width=True, config= {'displaylogo': False})
    st.caption('Feiertage die auf Wochenenden fallen gelten als Feiertage')


    # ÜBERSTUNDEN
    st.subheader('Überstunden')
    col1,col2,col3=st.columns(3)
    col1.metric('innerhalb Sollzeit', "{0:.0%}".format(main_df['Zeit-Saldo'][abs(main_df['Zeit-Saldo'])<=0.333].__len__() / len(main_df)), help='Die Sollzeit ist hierbei definiert als 7,6 Stunden +/- 20 Minuten')
    col2.metric('unterhalb Sollzeit', "{0:.0%}".format(main_df['Zeit-Saldo'][(main_df['Zeit-Saldo'])<-0.333].__len__() / len(main_df)))
    col3.metric('oberhalb Sollzeit', "{0:.0%}".format(main_df['Zeit-Saldo'][(main_df['Zeit-Saldo'])>0.333].__len__() / len(main_df)))
    fig = px.bar(
        main_df,
        x='Datum',
        y='Zeit-Saldo')
    st.plotly_chart(fig, use_container_width=True, config= {'displaylogo': False})


    # HOME-OFFICE
    st.subheader('Home-Office')
    col1, col2, col3 = st.columns(3)
    col1.metric('Arbeitstage', len(main_df))
    col2.metric('Home-Office Quote', "{0:.0%}".format(len(main_df[(main_df['Büro']=='Home-Office') ]) / len(main_df)))
    col3.metric('Büro Quote', "{0:.0%}".format(len(main_df[(main_df['Büro']=='Büro') ]) / len(main_df)))

    diff_homeoffice = int(0.4*len(main_df)) - len(main_df[(main_df['Büro']=='Büro')])
    if diff_homeoffice>0: 
        st.warning(str(diff_homeoffice) + ' Tage hättest du häufiger im Büro sein müssen')
    else:
        st.success(str(diff_homeoffice) + ' Tage müsstest du weniger im Büro sein müssen')

    fig = px.bar(main_df, x='Wochentag', color='Büro')
    st.plotly_chart(fig, use_container_width=True, config= {'displaylogo': False})

    fig = px.bar(main_df, x='Datum', y='Gesamt-Zeit')
    st.plotly_chart(fig, use_container_width=True, config= {'displaylogo': False})

    st.write(main_df['Vormittag-Zeit'].sum()/len(main_df))

    fig = px.bar(main_df, x='Wochentag', y=['Vormittag-Zeit', 'Pausen-Dauer', 'Nachmittag-Zeit'])
    st.plotly_chart(fig, use_container_width=True, config= {'displaylogo': False})


    # PAUSEN
    st.subheader('Pausen')
    col1, col2, col3, col4 = st.columns(4)
    col1.metric('Kürzeste Pause', str(round(main_df['Pause-Gesamt'].min(),1)).replace('.',',') + ' h')
    col2.metric('Mittlere Pause', str(round(main_df['Pause-Gesamt'].sum()/len(main_df),1)).replace('.',',') + ' h')
    col3.metric('Median Pause', str(round(main_df['Pause-Gesamt'].median(),1)).replace('.',',') + ' h')
    col4.metric('Längste Pause', str(round(main_df['Pause-Gesamt'].max(),1)).replace('.',',') + ' h')
    diff_pause_homeoffice = main_df[main_df['Büro']=='Büro']['Pausen-Dauer'].sum() / len(main_df[main_df['Büro']=='Büro']) - main_df[main_df['Büro']=='Home-Office']['Pausen-Dauer'].sum() / len(main_df[main_df['Büro']=='Home-Office'])
    
    if diff_pause_homeoffice < 0:
        st.info('Im Home-Office sind deine Pausen um ' + str(round(abs(diff_pause_homeoffice),1)).replace('.',',') + 'h bzw. ' + str(int(round(abs(diff_pause_homeoffice)*60,0))) + ' min. länger')
    else:
        st.info('Im Home-Office sind deine Pausen um ' + str(round(abs(diff_pause_homeoffice),1)).replace('.',',') + 'h kürzer')
    fig = px.histogram(main_df, x='Pause-Gesamt', color='Büro')
    st.plotly_chart(fig, use_container_width=True, config= {'displaylogo': False})

    st.info(str(len(main_df[main_df['Pause']==0.75])) + ' mal hast du deine Pause nicht ausgebucht (jeweils 45 min. Pause wird dir dafür gebucht)')
    st.write(str(round(main_df[main_df['Pause']!=0.75]['Pause'].sum(),1)).replace('.',',') + ' Stunden wurden dir darüber hinaus als Pausenzeit ausgebucht')


    # ARBEITSTAG
    st.header('Wie dein Arbeitstag unterteilt ist')
    st.write('**' + get_mean_time(main_df['Kommt']) + '** - dein Arbeitsalltag beginnt')
    st.write('**' + get_mean_time(main_df[main_df['Pause-Anfang'].notna()]['Pause-Anfang']) + '** - deine Pause wird angetreten')
    st.write('**' + get_mean_time(main_df[main_df['Pause-Ende'].notna()]['Pause-Ende']) + '** - du beendest deine Pause')
    st.write('**' + get_mean_time(main_df[main_df['Geht'].notna()]['Geht']) + '** - du gehst nach Hause')
    col1, col2, col3 = st.columns(3)
    col1.metric('Vormittags', "{0:.0%}".format(main_df['Vormittag-Zeit'].sum()/main_df['Gesamt-Zeit'].sum()))
    col2.metric('Pause', "{0:.0%}".format(main_df['Pausen-Dauer'].sum()/main_df['Gesamt-Zeit'].sum()))
    col3.metric('Nachmittag', "{0:.0%}".format(main_df['Nachmittag-Zeit'].sum()/main_df['Gesamt-Zeit'].sum()))

    fig = px.pie(
        main_df,
        names=['Vormittag', 'Pause', 'Nachmittag'],
        values=[
            round(main_df['Vormittag-Zeit'].sum()/len(main_df),1),
            round(main_df['Pausen-Dauer'].sum()/len(main_df),1),
            round(main_df['Nachmittag-Zeit'].sum()/len(main_df),1)
            ],
        labels=['a', 'b', 'c'])
    fig.update_traces(textposition='inside', textinfo='value+label')
    st.plotly_chart(fig, use_container_width=True, config= {'displaylogo': False})

from app.drive_client import DriveClient


def test_appsheet_signed_file_reference_extracts_file_name():
    value = (
        "gettablefileurl?appName=GDTransex-321562219"
        "&tableName=PEDIDO_FIERRO"
        "&fileName=FACTURAS_HORMIGON%2FFIERRO_PEDIDOS%2F"
        "65c4a65e.ARCHIVO_PEDIDO.013805.xls"
        "&appVersion=1.000395&signature=abc"
    )
    assert DriveClient._appsheet_file_path(value) == (
        "FACTURAS_HORMIGON/FIERRO_PEDIDOS/"
        "65c4a65e.ARCHIVO_PEDIDO.013805.xls"
    )
    assert DriveClient._basename(value) == (
        "65c4a65e.ARCHIVO_PEDIDO.013805.xls"
    )


def test_relative_appsheet_path_stays_unchanged():
    value = (
        "FACTURAS_HORMIGON/FIERRO_PEDIDOS/"
        "65c4a65e.ARCHIVO_PEDIDO.013805.xls"
    )
    assert DriveClient._appsheet_file_path(value) == value
    assert DriveClient._basename(value) == (
        "65c4a65e.ARCHIVO_PEDIDO.013805.xls"
    )

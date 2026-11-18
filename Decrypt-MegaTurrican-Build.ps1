[CmdletBinding()]
param(
    [string]$InputPath = ".\MegaTurrican-Windows-x64.zip.enc",
    [string]$OutputPath = ".\MegaTurrican-Windows-x64.zip"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $InputPath -PathType Leaf)) {
    throw "Encrypted build not found: $InputPath"
}

$secureKey = Read-Host "Enter the MEGATURRICAN_SOURCE_KEY Actions secret" -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
    $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
}

$payload = [System.IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $InputPath))
if ($payload.Length -lt 32 -or [System.Text.Encoding]::ASCII.GetString($payload, 0, 8) -ne "Salted__") {
    throw "The file is not a supported OpenSSL salted AES-256-CBC file."
}

$salt = New-Object byte[] 8
[Array]::Copy($payload, 8, $salt, 0, 8)

$cipherLength = $payload.Length - 16
$cipherText = New-Object byte[] $cipherLength
[Array]::Copy($payload, 16, $cipherText, 0, $cipherLength)

$kdf = [System.Security.Cryptography.Rfc2898DeriveBytes]::new(
    $password,
    $salt,
    600000,
    [System.Security.Cryptography.HashAlgorithmName]::SHA256
)
$material = $kdf.GetBytes(48)

$keyBytes = New-Object byte[] 32
$iv = New-Object byte[] 16
[Array]::Copy($material, 0, $keyBytes, 0, 32)
[Array]::Copy($material, 32, $iv, 0, 16)

$aes = [System.Security.Cryptography.Aes]::Create()
$aes.KeySize = 256
$aes.BlockSize = 128
$aes.Mode = [System.Security.Cryptography.CipherMode]::CBC
$aes.Padding = [System.Security.Cryptography.PaddingMode]::PKCS7
$aes.Key = $keyBytes
$aes.IV = $iv

$decryptor = $aes.CreateDecryptor()
try {
    $plainText = $decryptor.TransformFinalBlock($cipherText, 0, $cipherText.Length)
    $fullOutputPath = [System.IO.Path]::GetFullPath($OutputPath)
    [System.IO.File]::WriteAllBytes($fullOutputPath, $plainText)
    Write-Host "Decrypted build written to: $fullOutputPath"
}
catch {
    throw "Decryption failed. Check that the key is correct and the artifact downloaded completely."
}
finally {
    if ($decryptor) { $decryptor.Dispose() }
    if ($aes) { $aes.Dispose() }
    if ($kdf) { $kdf.Dispose() }
    $password = $null
    $plainText = $null
}

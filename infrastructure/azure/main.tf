
terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

variable "subscription_id" {
  type        = string
  description = "Azure for Students subscription ID"
}

variable "ssh_allowed_cidr" {
  type        = string
  description = "Your public IP address in CIDR format, e.g. 203.0.113.10/32"
}

variable "admin_username" {
  type    = string
  default = "azureuser"
}

variable "vm_size" {
  type        = string
  description = "Validate price and availability before deployment"
  default     = "Standard_B2as_v2"
}

locals {
  project_name = "nexora"
  location     = "India South Central"
}

resource "azurerm_resource_group" "nexora" {
  name     = "nexora-azure-rg"
  location = local.location

  tags = {
    project     = "Nexora"
    environment = "portfolio"
    managed_by  = "Terraform"
  }
}

resource "azurerm_virtual_network" "nexora" {
  name                = "nexora-vnet"
  location            = azurerm_resource_group.nexora.location
  resource_group_name = azurerm_resource_group.nexora.name
  address_space       = ["10.20.0.0/16"]
}

resource "azurerm_subnet" "nexora" {
  name                 = "nexora-subnet"
  resource_group_name  = azurerm_resource_group.nexora.name
  virtual_network_name = azurerm_virtual_network.nexora.name
  address_prefixes     = ["10.20.1.0/24"]
}

resource "azurerm_network_security_group" "nexora" {
  name                = "nexora-nsg"
  location            = azurerm_resource_group.nexora.location
  resource_group_name = azurerm_resource_group.nexora.name

  security_rule {
    name                       = "SSH-Restricted"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = var.ssh_allowed_cidr
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "HTTP"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "80"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "HTTPS"
    priority                   = 120
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "nexora" {
  subnet_id                 = azurerm_subnet.nexora.id
  network_security_group_id = azurerm_network_security_group.nexora.id
}

resource "azurerm_public_ip" "nexora" {
  name                = "nexora-public-ip"
  location            = azurerm_resource_group.nexora.location
  resource_group_name = azurerm_resource_group.nexora.name
  allocation_method   = "Static"
  sku                 = "Standard"
}

resource "azurerm_network_interface" "nexora" {
  name                = "nexora-nic"
  location            = azurerm_resource_group.nexora.location
  resource_group_name = azurerm_resource_group.nexora.name

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.nexora.id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.nexora.id
  }
}

resource "azurerm_network_interface_security_group_association" "nexora" {
  network_interface_id      = azurerm_network_interface.nexora.id
  network_security_group_id = azurerm_network_security_group.nexora.id
}

resource "azurerm_linux_virtual_machine" "nexora" {
  name                = "nexora-k3s-vm"
  computer_name       = "nexora-k3s"
  resource_group_name = azurerm_resource_group.nexora.name
  location            = azurerm_resource_group.nexora.location
  size                = var.vm_size
  admin_username      = var.admin_username

  network_interface_ids = [
    azurerm_network_interface.nexora.id
  ]

  disable_password_authentication = true

  admin_ssh_key {
    username   = var.admin_username
    public_key = file(pathexpand("~/.ssh/id_ed25519.pub"))
  }

  os_disk {
    name                 = "nexora-os-disk"
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
    disk_size_gb         = 64
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  custom_data = base64encode(<<-CLOUDINIT
    #cloud-config
    package_update: true
    packages:
      - curl
      - openssl
    runcmd:
      - [sh, -c, "curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC='server' sh -"]
      - [sh, -c, "curl -fsSL https://raw.githubusercontent.com/ManuRaj05/nexora/main/infrastructure/azure/scripts/bootstrap-argocd.sh -o /root/bootstrap-argocd.sh && chmod +x /root/bootstrap-argocd.sh && /root/bootstrap-argocd.sh"]
  CLOUDINIT
  )

  tags = {
    project     = "Nexora"
    environment = "portfolio"
    managed_by  = "Terraform"
  }
}

output "vm_public_ip" {
  value       = azurerm_public_ip.nexora.ip_address
  description = "Public IP for SSH and web access"
}

output "ssh_command" {
  value = "ssh ${var.admin_username}@${azurerm_public_ip.nexora.ip_address}"
}

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE retailers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    code VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    base_url VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE skus (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ean_gtin VARCHAR(14) UNIQUE,
    internal_code VARCHAR(50),
    brand VARCHAR(100) NOT NULL,
    title VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE retail_categories (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    retailer_id UUID NOT NULL REFERENCES retailers(id) ON DELETE CASCADE,
    name VARCHAR(150) NOT NULL,
    category_url VARCHAR(500) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE monitoring_configs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(150) NOT NULL,
    retailer_id UUID NOT NULL REFERENCES retailers(id) ON DELETE RESTRICT,
    sku_id UUID REFERENCES skus(id) ON DELETE CASCADE,
    category_id UUID REFERENCES retail_categories(id) ON DELETE CASCADE,
    search_keyword VARCHAR(255),
    frequency_hours INT NOT NULL DEFAULT 6,
    start_date TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    end_date TIMESTAMP WITH TIME ZONE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_target CHECK (
        (sku_id IS NOT NULL AND category_id IS NULL AND search_keyword IS NULL) OR
        (sku_id IS NULL AND category_id IS NOT NULL AND search_keyword IS NULL) OR
        (sku_id IS NULL AND category_id IS NULL AND search_keyword IS NOT NULL)
    )
);

CREATE TABLE scraping_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    config_id UUID NOT NULL REFERENCES monitoring_configs(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'RUNNING',
    started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT
);

CREATE TABLE daily_digital_shelf_metrics (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES scraping_runs(id) ON DELETE CASCADE,
    retailer_id UUID NOT NULL REFERENCES retailers(id),
    sku_id UUID REFERENCES skus(id),
    search_keyword VARCHAR(255),
    search_position INT,
    category_position INT,
    is_sponsored BOOLEAN DEFAULT FALSE,
    banner_presence BOOLEAN DEFAULT FALSE,
    promotion_tag VARCHAR(150),
    base_price NUMERIC(12, 2) NOT NULL,
    discount_price NUMERIC(12, 2),
    discount_percentage NUMERIC(5, 2) GENERATED ALWAYS AS (
        CASE 
            WHEN base_price > 0 AND discount_price IS NOT NULL 
            THEN ROUND(((base_price - discount_price) / base_price) * 100, 2)
            ELSE 0 
        END
    ) STORED,
    in_stock BOOLEAN NOT NULL DEFAULT TRUE,
    captured_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);